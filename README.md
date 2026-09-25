# 域名拦截代理

基于 mitmproxy 的域名拦截转发工具，提供图形化界面管理域名映射规则，支持 HTTP/HTTPS 请求拦截与域名重写。

## 功能特性

- 图形化界面管理域名映射规则（添加、删除、双击单元格就地修改）
- 支持 HTTP/HTTPS 请求拦截与域名重写
- 兼容 HTTP/2（自动同步 `:authority` 伪头与 SNI）
- 自动匹配子域名（配置 `huggingface.co` 同时命中 `cdn.huggingface.co`）
- 自动开启/关闭系统代理，退出时强制清理
- 一键安装 CA 证书到系统信任库，启动时自动检测证书状态
- 实时运行日志显示（上限 1000 行，超出自动裁剪）
- 配置修改后自动重启代理生效
- 启动前检查端口占用，避免端口冲突

## 快速开始

### 使用打包版本

1. 从 [Releases](https://github.com/ZhengHaoF/proxy-route/releases) 下载最新版本的 zip 文件
2. 解压到任意目录（目录中应包含 `proxy_gui.exe` 和 `mitmdump` 文件夹）
3. 双击 `proxy_gui.exe` 启动
4. 点击「启动代理」，首次启动会自动生成 CA 证书
5. 点击「安装 CA 证书」把证书写入系统信任库，然后重启浏览器
6. 之后点击「启动代理」即可使用

### 开发模式

程序在开发模式下固定调用 `venv\Scripts\mitmdump.exe`，因此必须先创建虚拟环境并安装 mitmproxy：

```bash
python -m venv venv
venv\Scripts\pip.exe install mitmproxy
```

启动方式二选一：

```bash
:: 方式一：使用批处理脚本（内部调用 venv 中的解释器）
start_gui.bat

:: 方式二：直接运行
venv\Scripts\python.exe proxy_gui.py
```

## 配置

域名映射规则存储在 `domain_mapping.json` 中：

```json
{
  "mappings": {
    "huggingface.co": "hf-mirror.com"
  },
  "proxy_port": 8123
}
```

- `mappings`：源域名到目标域名的映射，命中规则时会同时匹配其所有子域名
- `proxy_port`：仅作记录用途。代理端口当前固定为 `8123`，由 `proxy_gui.py` 中的常量 `PROXY_PORT` 决定，修改该字段不会改变实际监听端口

## 工作原理

1. 启动后在本地 `127.0.0.1:8123` 开启 HTTP 代理
2. 自动设置系统代理，所有 HTTP/HTTPS 流量经过代理
3. `domain_rewriter.py` 作为 mitmproxy 插件加载，通过两个钩子共同完成改写：
   - `server_connect`：在连接上游服务器之前改写连接目标，并同步 SNI，否则 TLS 握手会因域名不匹配而失败
   - `request`：改写 `flow.request.host`，同步 HTTP/2 的 `:authority` 伪头和 `Host` 头（只改 `Host` 头会导致目标站点返回空响应）
4. 匹配映射规则后，将请求的目标域名改写到目标域名
5. mitmproxy 关键启动参数：`--ssl-insecure`（跳过上游证书校验）、`connection_strategy=lazy`（延迟连接，避免提前连到旧目标）、`confdir` 指向 `.mitmproxy` 证书目录
6. 退出时自动清理系统代理设置

## 注意事项

- 仅支持 Windows 系统
- 首次使用需安装 CA 证书（用于 HTTPS 拦截），且必须先启动一次代理生成证书文件后再安装
- 关闭软件时会自动清理系统代理设置，如异常退出请手动关闭系统代理
