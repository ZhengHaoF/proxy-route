"""
域名拦截代理 - 桌面管理工具
"""
import json
import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime


def _resource_dir():
    """资源目录：打包后为 exe 所在目录，开发时为脚本所在目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_FILE = os.path.join(_resource_dir(), 'domain_mapping.json')
PROXY_PORT = 8123
MAX_LOG_LINES = 1000   # 日志最大行数，超过后裁剪
TRIM_LOG_TO = 500      # 超限时裁剪保留的行数


class ProxyGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("域名拦截代理")
        self.root.geometry("560x680")
        self.root.resizable(False, False)

        self.proxy_process = None
        self.proxy_running = False
        self._log_reader_thread = None
        self._edit_entry = None
        self._edit_item = None
        self._edit_col_index = 0
        self._build_ui()
        self._load_config()
        self._log("系统就绪")

    def _build_ui(self):
        # ---- 代理状态区 ----
        status_frame = ttk.LabelFrame(self.root, text="代理状态", padding=10)
        status_frame.pack(fill="x", padx=12, pady=(12, 6))

        row = ttk.Frame(status_frame)
        row.pack(fill="x")

        self.status_label = ttk.Label(row, text="● 已停止", foreground="gray", font=("", 11, "bold"))
        self.status_label.pack(side="left")

        self.start_btn = ttk.Button(row, text="启动代理", command=self._toggle_proxy)
        self.start_btn.pack(side="right")

        info = ttk.Frame(status_frame)
        info.pack(fill="x", pady=(6, 0))
        ttk.Label(info, text=f"端口: {PROXY_PORT}  |  地址: 127.0.0.1:{PROXY_PORT}",
                  foreground="#666").pack(side="left")

        self.sysproxy_label = ttk.Label(status_frame,
                                        text="系统代理: 已关闭",
                                        foreground="gray")
        self.sysproxy_label.pack(anchor="w", pady=(4, 0))

        # ---- 域名映射区 ----
        mapping_frame = ttk.LabelFrame(self.root, text="域名映射规则", padding=10)
        mapping_frame.pack(fill="both", expand=True, padx=12, pady=6)

        columns = ("src", "arrow", "dst")
        self.tree = ttk.Treeview(mapping_frame, columns=columns, show="headings", height=5)
        self.tree.column("src", width=160, anchor="center")
        self.tree.column("arrow", width=40, anchor="center")
        self.tree.column("dst", width=160, anchor="center")
        self.tree.heading("src", text="源域名")
        self.tree.heading("arrow", text="")
        self.tree.heading("dst", text="目标域名")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # 顶部按钮行：添加 / 删除选中（靠右对齐）
        top_row = ttk.Frame(mapping_frame)
        top_row.pack(fill="x", pady=(8, 0))
        ttk.Button(top_row, text="删除选中", command=self._del_mapping).pack(side="right")
        ttk.Button(top_row, text="添加", command=self._add_mapping).pack(side="right", padx=(0, 4))

        # ---- 快捷操作区 ----
        action_frame = ttk.LabelFrame(self.root, text="快捷操作", padding=10)
        action_frame.pack(fill="x", padx=12, pady=(6, 6))

        btn_row = ttk.Frame(action_frame)
        btn_row.pack()

        ttk.Button(btn_row, text="安装 CA 证书", command=self._install_cert).pack(side="left", padx=6)
        ttk.Button(btn_row, text="清除日志", command=self._clear_log).pack(side="left", padx=6)

        # ---- 日志区 ----
        log_frame = ttk.LabelFrame(self.root, text="运行日志", padding=6)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=10, font=("Consolas", 9),
            state="disabled", bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white"
        )
        self.log_text.pack(fill="both", expand=True)

    def _is_system_proxy_on(self):
        """检查系统代理是否开启"""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_READ
            )
            value, _ = winreg.QueryValueEx(key, "ProxyEnable")
            winreg.CloseKey(key)
            return value == 1
        except Exception:
            return False

    def _log(self, msg, level="INFO"):
        """添加日志到文本框，超过最大行数时自动裁剪"""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {msg}\n"
        self.log_text.config(state="normal")
        self.log_text.insert("end", line)

        # 限制日志最大行数：超过 MAX_LOG_LINES 时删到 TRIM_LOG_TO 行
        current_lines = int(self.log_text.index("end-1c").split(".")[0])
        if current_lines > MAX_LOG_LINES:
            keep_from = current_lines - TRIM_LOG_TO
            self.log_text.delete("1.0", f"{keep_from}.0")

        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        """清空日志区"""
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self._log("日志已清除")

    def _read_process_output(self):
        """后台线程：读取代理进程输出"""
        try:
            while self.proxy_process and self.proxy_process.poll() is None:
                line = self.proxy_process.stdout.readline()
                if line:
                    text = line.decode('utf-8', errors='replace').strip()
                    if text:
                        self.root.after(0, self._log, text)
                else:
                    break
        except Exception as e:
            self.root.after(0, self._log, f"读取输出异常: {e}", "ERROR")

        if self.proxy_process:
            code = self.proxy_process.wait()
            # 捕获 stderr 中的错误信息
            if self.proxy_process.stderr:
                try:
                    stderr_text = self.proxy_process.stderr.read().decode('utf-8', errors='replace').strip()
                    if stderr_text:
                        self.root.after(0, self._log, f"stderr: {stderr_text}", "ERROR")
                except Exception:
                    pass
            self.proxy_process = None
            if self.proxy_running:
                self.root.after(0, self._on_proxy_crashed, code)

    def _on_proxy_crashed(self, exit_code):
        """代理进程意外退出"""
        self.proxy_running = False
        self.status_label.config(text="● 已停止 (异常退出)", foreground="red")
        self.start_btn.config(text="启动代理")
        self._log(f"代理进程异常退出, 退出码: {exit_code}", "ERROR")

    def _load_config(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            mappings = config.get('mappings', {})
            for src, dst in mappings.items():
                self.tree.insert("", "end", values=(src, "→", dst))
        except Exception as e:
            self._log(f"加载配置失败: {e}", "ERROR")

    def _save_config(self):
        mappings = {}
        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            mappings[vals[0]] = vals[2]
        config = {"mappings": mappings, "proxy_port": PROXY_PORT}
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        # 配置已修改，若代理在运行则自动重启使其立即生效
        self._restart_proxy()

    def _restart_proxy(self):
        """配置修改后自动重启代理，使新映射立即生效"""
        if not self.proxy_running:
            return
        self._log("检测到配置修改，自动重启代理...", "WARN")
        self._stop_proxy()
        self._start_proxy()

    def _add_mapping(self):
        """弹窗添加映射"""
        win = tk.Toplevel(self.root)
        win.title("添加映射")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="源域名:").grid(row=0, column=0, sticky="w", pady=4)
        src_var = tk.StringVar()
        src_entry = ttk.Entry(frm, textvariable=src_var, width=28)
        src_entry.grid(row=0, column=1, padx=8, pady=4)

        ttk.Label(frm, text="目标域名:").grid(row=1, column=0, sticky="w", pady=4)
        dst_var = tk.StringVar()
        ttk.Entry(frm, textvariable=dst_var, width=28).grid(row=1, column=1, padx=8, pady=4)

        def do_add():
            src = src_var.get().strip()
            dst = dst_var.get().strip()
            if not src or not dst:
                messagebox.showwarning("提示", "请输入源域名和目标域名", parent=win)
                return
            for item in self.tree.get_children():
                if self.tree.item(item, "values")[0] == src:
                    messagebox.showwarning("提示", f"域名 {src} 已存在", parent=win)
                    return
            self.tree.insert("", "end", values=(src, "→", dst))
            self._save_config()
            self._log(f"添加映射: {src} → {dst}")
            win.destroy()

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=2, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btn_row, text="确定", width=8, command=do_add).pack(side="left", padx=6)
        ttk.Button(btn_row, text="取消", width=8, command=win.destroy).pack(side="left", padx=6)

        src_entry.focus_set()
        win.bind("<Return>", lambda e: do_add())
        win.bind("<Escape>", lambda e: win.destroy())

    def _del_mapping(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选中要删除的行")
            return
        for item in selected:
            vals = self.tree.item(item, "values")
            self._log(f"删除映射: {vals[0]} → {vals[2]}")
            self.tree.delete(item)
        self._save_config()

    def _on_tree_double_click(self, event):
        """双击单元格 -> 弹出就地编辑框"""
        # 若已有编辑框，先提交
        if self._edit_entry is not None:
            self._commit_edit()
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not item or column == "#2":  # 箭头列不可编辑
            return
        col_index = {"#1": 0, "#3": 2}[column]
        x, y, width, height = self.tree.bbox(item, column)
        values = list(self.tree.item(item, "values"))

        self._edit_entry = ttk.Entry(self.tree)
        self._edit_entry.place(x=x, y=y, width=width, height=height)
        self._edit_entry.insert(0, values[col_index])
        self._edit_item = item
        self._edit_col_index = col_index
        self._edit_entry.focus_set()
        self._edit_entry.select_range(0, "end")
        self._edit_entry.bind("<Return>", self._commit_edit)
        self._edit_entry.bind("<Escape>", self._cancel_edit)
        self._edit_entry.bind("<FocusOut>", self._commit_edit)

    def _commit_edit(self, event=None):
        """提交编辑内容"""
        if self._edit_entry is None:
            return
        new_value = self._edit_entry.get().strip()
        item = self._edit_item
        col_index = self._edit_col_index
        self._destroy_edit()
        if not new_value:
            self._log("编辑内容不能为空", "WARN")
            return
        values = list(self.tree.item(item, "values"))
        # 校验源域名不与其他行重复
        if col_index == 0:
            for child in self.tree.get_children():
                if child != item and self.tree.item(child, "values")[0] == new_value:
                    self._log(f"域名 {new_value} 已存在", "WARN")
                    return
        if values[col_index] != new_value:
            values[col_index] = new_value
            self.tree.item(item, values=values)
            self._save_config()
            self._log(f"更新映射: {values[0]} → {values[2]}")

    def _cancel_edit(self, event=None):
        """取消编辑"""
        self._destroy_edit()

    def _destroy_edit(self):
        if self._edit_entry is not None:
            self._edit_entry.destroy()
            self._edit_entry = None

    def _toggle_proxy(self):
        if self.proxy_running:
            self._stop_proxy()
        else:
            self._start_proxy()

    def _start_proxy(self):
        import time
        t0 = time.time()
        def _t(label):
            self._log(f"[计时] {label}: {time.time()-t0:.3f}s")

        script_dir = _resource_dir()
        addon_path = os.path.join(script_dir, 'domain_rewriter.py')

        if getattr(sys, 'frozen', False):
            mitmdump_exe = os.path.join(script_dir, 'mitmdump', 'mitmdump.exe')
        else:
            mitmdump_exe = os.path.join(script_dir, 'venv', 'Scripts', 'mitmdump.exe')

        cert_dir = os.path.join(script_dir, '.mitmproxy')
        _t("路径计算")

        if not os.path.exists(mitmdump_exe):
            self._log(f"mitmdump 不存在: {mitmdump_exe}", "ERROR")
            return
        if not os.path.exists(addon_path):
            self._log(f"插件脚本不存在: {addon_path}", "ERROR")
            return

        if self._is_port_in_use(PROXY_PORT):
            self._log(f"端口 {PROXY_PORT} 已被占用，请先关闭占用进程", "ERROR")
            messagebox.showerror("端口被占用", f"端口 {PROXY_PORT} 已被占用。\n请先关闭占用该端口的进程后再启动。")
            return
        _t("端口检查")

        # CA 证书检查与提示
        cert_path = os.path.join(cert_dir, 'mitmproxy-ca-cert.cer')
        if os.path.exists(cert_path):
            if not self._is_cert_installed():
                self._log("检测到 CA 证书尚未安装", "WARN")
                if messagebox.askyesno("证书未安装",
                                       "检测到 CA 证书尚未安装到系统信任库，\n"
                                       "HTTPS 网站可能无法正常访问。\n\n"
                                       "是否现在安装？"):
                    self._install_cert()
        else:
            self._log("首次启动，将自动生成 CA 证书。生成后请安装证书，HTTPS 才能正常访问。", "WARN")
        _t("证书检查")

        cmd = [
            mitmdump_exe,
            '-s', addon_path,
            '--listen-port', str(PROXY_PORT),
            '--set', f'confdir={cert_dir}',
            '--ssl-insecure',  # 禁用上游 TLS 证书校验（域名重定向场景必须）
            '--set', 'connection_strategy=lazy',  # 延迟连接，避免提前连接到旧目标
        ]

        self._log(f"启动代理, 端口={PROXY_PORT}, 证书目录={cert_dir}")

        try:
            self.proxy_process = subprocess.Popen(
                cmd,
                cwd=script_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            _t("Popen返回")
            self.proxy_running = True
            self.status_label.config(text="● 运行中", foreground="#22aa22")
            self.start_btn.config(text="停止代理")

            self._log_reader_thread = threading.Thread(target=self._read_process_output, daemon=True)
            self._log_reader_thread.start()
            _t("读线程启动")

            # 代理启动成功后，自动开启系统代理（静默，不弹窗）
            self._enable_system_proxy(silent=True)
            _t("系统代理设置")

        except Exception as e:
            self._log(f"启动失败: {e}", "ERROR")

    def _is_port_in_use(self, port):
        """检查端口是否被占用"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return False
            except OSError:
                return True

    def _stop_proxy(self):
        self._log("正在停止代理...")
        if self.proxy_process:
            self.proxy_process.terminate()
            try:
                self.proxy_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proxy_process.kill()
            self.proxy_process = None
        self.proxy_running = False
        self.status_label.config(text="● 已停止", foreground="gray")
        self.start_btn.config(text="启动代理")
        self._log("代理已停止")
        # 代理停止后自动关闭系统代理（静默，不弹窗）
        self._disable_system_proxy(silent=True)

    def _is_cert_installed(self):
        """检查 mitmproxy CA 证书是否已安装到当前用户信任库
        优先用 ctypes 直接查 Windows 证书库（快），失败时回退 certutil"""
        try:
            return self._is_cert_installed_ctypes()
        except Exception:
            return self._is_cert_installed_certutil()

    def _is_cert_installed_ctypes(self):
        """用 Windows crypto API 直接查询，避免 certutil 子进程开销"""
        import ctypes
        from ctypes import wintypes

        CERT_STORE_PROV_SYSTEM = 10
        CERT_SYSTEM_STORE_CURRENT_USER = 0x00010000
        CERT_STORE_READONLY_FLAG = 0x00008000
        X509_ASN_ENCODING = 0x00000001
        PKCS_7_ASN_ENCODING = 0x00010000
        CERT_FIND_SUBJECT_STR = 0x00080007

        crypt32 = ctypes.windll.crypt32
        crypt32.CertOpenStore.restype = wintypes.HANDLE
        crypt32.CertOpenStore.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
        crypt32.CertFindCertificateInStore.restype = wintypes.HANDLE
        crypt32.CertFindCertificateInStore.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.HANDLE]
        crypt32.CertFreeCertificateContext.argtypes = [wintypes.HANDLE]
        crypt32.CertCloseStore.argtypes = [wintypes.HANDLE, wintypes.DWORD]

        hStore = crypt32.CertOpenStore(
            CERT_STORE_PROV_SYSTEM, 0, 0,
            CERT_SYSTEM_STORE_CURRENT_USER | CERT_STORE_READONLY_FLAG,
            ctypes.c_wchar_p("ROOT")
        )
        if not hStore:
            return False
        try:
            cert_ctx = crypt32.CertFindCertificateInStore(
                hStore, X509_ASN_ENCODING | PKCS_7_ASN_ENCODING, 0,
                CERT_FIND_SUBJECT_STR, ctypes.c_wchar_p("mitmproxy"), None
            )
            if cert_ctx:
                crypt32.CertFreeCertificateContext(cert_ctx)
                return True
            return False
        finally:
            crypt32.CertCloseStore(hStore, 0)

    def _is_cert_installed_certutil(self):
        """回退方案：用 certutil 查询"""
        try:
            result = subprocess.run(
                ['certutil', '-store', '-user', 'Root'],
                capture_output=True, text=True, errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10
            )
            output = (result.stdout or '') + (result.stderr or '')
            return 'mitmproxy' in output.lower()
        except Exception:
            return False

    def _install_cert(self):
        script_dir = _resource_dir()
        cert_dir = os.path.join(script_dir, '.mitmproxy')
        cert_path = os.path.join(cert_dir, 'mitmproxy-ca-cert.cer')

        self._log(f"检查证书: {cert_path}")

        if not os.path.exists(cert_path):
            self._log("证书文件不存在，请先启动代理生成证书", "WARN")
            messagebox.showwarning("提示",
                "证书文件不存在，请先启动一次代理生成证书。\n"
                f"预期路径: {cert_path}")
            return

        self._log("正在安装 CA 证书到系统信任库...")
        try:
            # 安装到当前用户 + 本地机器（双重保险）
            for store in ['-user', 'LOCAL_MACHINE']:
                try:
                    result = subprocess.run(
                        ['certutil', '-addstore', store, 'ROOT', cert_path],
                        check=True, capture_output=True
                    )
                    output = result.stdout.decode('gbk', errors='replace')
                    self._log(f"certutil ({store}) 输出: {output.strip()}")
                except subprocess.CalledProcessError as e:
                    err = e.stderr.decode('gbk', errors='replace') if e.stderr else str(e)
                    self._log(f"certutil ({store}) 失败: {err}", "WARN")
            self._log("CA 证书安装完成！", "OK")
            messagebox.showinfo("成功", "CA 证书已安装到系统信任库！\n请重启浏览器后重试。")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode('gbk', errors='replace') if e.stderr else str(e)
            self._log(f"证书安装失败: {err}", "ERROR")
            messagebox.showerror("错误", f"证书安装失败:\n{err}")
        except Exception as e:
            self._log(f"证书安装异常: {e}", "ERROR")
            messagebox.showerror("错误", f"证书安装失败:\n{e}")

    def _enable_system_proxy(self, silent=False):
        """开启系统代理，silent=True 时不弹窗（用于启动代理时自动开启）"""
        if not silent:
            self._log("开启系统代理...")
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{PROXY_PORT}")
            winreg.CloseKey(key)
            self.sysproxy_label.config(text="系统代理: 已开启", foreground="#22aa22")
            self._log(f"系统代理已开启: 127.0.0.1:{PROXY_PORT}", "OK")
            if not silent:
                messagebox.showinfo("成功", f"系统代理已开启: 127.0.0.1:{PROXY_PORT}")
        except Exception as e:
            self._log(f"开启系统代理失败: {e}", "ERROR")
            if not silent:
                messagebox.showerror("错误", f"设置失败:\n{e}")

    def _disable_system_proxy(self, silent=False):
        """关闭系统代理，silent=True 时不弹窗（用于互斥自动关闭）"""
        if not silent:
            self._log("关闭系统代理...")
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            self.sysproxy_label.config(text="系统代理: 已关闭", foreground="gray")
            if not silent:
                self._log("系统代理已关闭", "OK")
                messagebox.showinfo("成功", "系统代理已关闭")
        except Exception as e:
            if not silent:
                self._log(f"关闭系统代理失败: {e}", "ERROR")
                messagebox.showerror("错误", f"设置失败:\n{e}")
            else:
                self._log(f"关闭系统代理失败: {e}", "ERROR")

    def on_close(self):
        """退出：停止代理 + 强制关闭系统代理"""
        if self.proxy_running:
            self._stop_proxy()
        # 总是强制关闭系统代理（避免用户关掉软件后断网）
        if self._is_system_proxy_on():
            self._log("退出时强制关闭系统代理...", "WARN")
            self._disable_system_proxy(silent=True)
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ProxyGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
