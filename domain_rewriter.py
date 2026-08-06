"""
mitmproxy addon: 域名拦截转发
读取 domain_mapping.json 配置，将匹配的域名请求转发到目标域名

关键：用 server_connect 钩子在"连接上游服务器之前"改写目标地址
（http_connect 钩子文档明确说"can be ignored for most practical purposes"，改写无效）
"""
import json
import logging
import os
from mitmproxy import http
from mitmproxy.proxy import server_hooks

log = logging.getLogger(__name__)


class DomainRewriter:
    def __init__(self):
        self.mappings = {}
        self.load_config()

    def load_config(self):
        """加载域名映射配置"""
        config_path = os.path.join(os.path.dirname(__file__), 'domain_mapping.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.mappings = config.get('mappings', {})
                log.info(f"已加载 {len(self.mappings)} 条域名映射规则")
                for src, dst in self.mappings.items():
                    log.info(f"  {src} -> {dst}")
        except Exception as e:
            log.error(f"加载配置文件失败: {e}")

    def _rewrite_host(self, host):
        """匹配并改写主机名，返回 (新host, 是否改写)"""
        if not host:
            return host, False
        # 去掉端口号
        pure_host = host.split(':')[0]
        for src_domain, dst_domain in self.mappings.items():
            if pure_host == src_domain or pure_host.endswith(f'.{src_domain}'):
                return dst_domain, True
        return host, False

    def server_connect(self, data: server_hooks.ServerConnectionHookData):
        """mitmproxy 即将连接上游服务器 —— 这是改写连接目标的正确时机"""
        server = data.server
        if not server.address:
            return

        host, port = server.address
        new_host, changed = self._rewrite_host(host)
        if changed:
            # 改写连接目标（mitmproxy 会连接到 new_host:port）
            server.address = (new_host, port)
            # 关键：同步设置 SNI，否则 TLS 握手会用旧域名导致失败
            server.sni = new_host
            log.info(f"[REWRITE] {host}:{port} -> {new_host}:{port}")

    def request(self, flow: http.HTTPFlow):
        """HTTP / HTTPS 请求拦截 —— 改写请求目标域名

        关键：必须通过 flow.request.host 改写，而不只是 headers['Host']。
        因为 HTTP/2 的目标域名是 :authority 伪头，不是普通的 Host header；
        只改 Host header 会导致发给目标站点的请求仍带着原域名，
        目标站点（如 hf-mirror.com 这类反代）识别不出来就会返回空响应导致白屏。
        设置 flow.request.host 会同步更新 :authority 伪头和 Host header。
        """
        host = flow.request.pretty_host
        new_host, changed = self._rewrite_host(host)
        if changed:
            old_url = flow.request.pretty_url
            # 设置 flow.request.host 会自动更新 pretty_host 和 HTTP/2 的 :authority 伪头
            flow.request.host = new_host
            # 显式同步 Host header（仅对 HTTP/1.x 生效，HTTP/2 用 :authority 伪头）
            flow.request.headers['Host'] = new_host
            log.info(f"[REWRITE-HOST] {host} -> {new_host} ({flow.request.scheme}) "
                     f"{old_url} -> {flow.request.pretty_url}")


addons = [DomainRewriter()]
