# 域名拦截代理

基于 mitmproxy 的域名拦截转发工具，提供图形化界面管理域名映射规则，支持 HTTP/HTTPS 请求拦截与域名重写。

## 功能特性

- 图形化界面管理域名映射规则（增删改）
- 支持 HTTP/HTTPS 请求拦截与域名重写
- 兼容 HTTP/2（自动同步 `:authority` 伪头）
- 自动开启/关闭系统代理
- 一键安装 CA 证书到系统信任库
- 实时运行日志显示
- 配置修改后自动重启代理生效

## 快速开始

### 使用打包版本

1. 从 [Releases](https://github.com/ZhengHaoF/proxy-route/releases) 下载最新版本的 zip 文件
2. 解压到任意目录
3. 双击 `proxy_gui.exe` 启动
4. 首次运行点击「安装 CA 证书」
5. 点击「启动代理」即可使用

### 开发模式

```bash
# 安装依赖
pip install mitmproxy

# 启动 GUI
python proxy_gui.py
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

- `mappings`：源域名到目标域名的映射
- `proxy_port`：代理监听端口（默认 8123）

## 工作原理

1. 启动后在本地 `127.0.0.1:8123` 开启 HTTP 代理
2. 自动设置系统代理，所有 HTTP/HTTPS 流量经过代理
3. `domain_rewriter.py` 作为 mitmproxy 插件，在连接上游服务器前拦截请求
4. 匹配映射规则后，将请求的目标域名和 SNI 改写到目标域名
5. 退出时自动清理系统代理设置

## 注意事项

- 仅支持 Windows 系统
- 首次使用需安装 CA 证书（用于 HTTPS 拦截）
- 关闭软件时会自动清理系统代理设置，如异常退出请手动关闭系统代理
