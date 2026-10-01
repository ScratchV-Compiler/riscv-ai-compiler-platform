# 网页 Demo 挂载指南

> 文档版本：v1.0
> 编写日期：2026-09-29
> 涉及模块：`app.py`（Flask 入口）、`.venv/`（已装依赖）、`templates/`、`static/`
> 适用场景：把本仓的 Flask 网页 Demo 跑起来，供本机 / 局域网 / 远程访问

本仓的"网页 Demo"就是 Flask 应用 `app.py`（默认 `0.0.0.0:5000`）。
下面按 **先验证 → 常驻运行 → 远程访问 → 生产托管** 的顺序给出可复制的命令。
以下命令均在本仓根目录执行（`/root/Lab/fuck_students/riscv-ai-compiler-platform`）。

---

## 一、最快挂载（开发服务器，适合本机/内网演示）

依赖已经装在仓内 `.venv`，无需重装。若换机器则先 `pip install -r requirements.txt`。

```bash
# 方式 A：直接用仓内解释器（推荐，不污染全局 Python）
.venv/bin/python app.py
```

```bash
# 方式 B：激活虚拟环境后再跑
source .venv/bin/activate
python app.py
```

启动成功会看到：

```
* Running on all addresses (0.0.0.0)
* Running on http://127.0.0.1:5000
* Running on http://192.168.0.107:5000
```

访问地址：

- 本机：<http://127.0.0.1:5000>
- 局域网其它设备：`http://192.168.0.107:5000`（本机内网 IP）

停止：前台按 `Ctrl+C`。注意当前 `app.py` 是 `debug=True`，会启动 reloader 子进程，普通 `Ctrl+C` 后建议确认端口已释放（见 §六）。

### 可访问的页面 / 接口

| 路径 | 说明 |
|---|---|
| `/` | 首页（含排行榜预览） |
| `/problems`、`/problems/<fwht\|conv\|spmv>` | 赛题列表 / 详情 |
| `/standings` | 排行榜（`?problem=all&stage=1`） |
| `/help` | 帮助页 |
| `/result/<id>` | 结果详情页（前端 2s 轮询） |
| `/api/problems`、`/api/result/<id>`、`/api/leaderboard/<problem>` | JSON 接口 |
| `/api/submit` | `POST` 提交（team/problem/code） |
| `/frag/standings` | htmx 片段 |

> `platform.db` 会在首次启动时由 `db.create_all()` 自动建表，无需手工初始化。

---

## 二、后台常驻运行（关掉终端也不停）

### 方式 1：nohup（最省事）

```bash
nohup .venv/bin/python app.py > run.log 2>&1 &
echo $! > app.pid          # 记录 PID，便于停止
```

查看日志 / 停止：

```bash
tail -f run.log            # 看启动与请求日志
kill "$(cat app.pid)"      # 停止
```

### 方式 2：systemd（开机自启、崩溃自动拉起，适合长期挂载）

新建 `/etc/systemd/system/riscv-platform.service`：

```ini
[Unit]
Description=RISC-V AI Compiler Platform (Flask demo)
After=network.target

[Service]
WorkingDirectory=/root/Lab/fuck_students/riscv-ai-compiler-platform
ExecStart=/root/Lab/fuck_students/riscv-ai-compiler-platform/.venv/bin/python app.py
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now riscv-platform
sudo systemctl status riscv-platform
journalctl -u riscv-platform -f     # 看日志
```

> 生产用途请先把 `app.py` 末尾的 `debug=True` 去掉（见 §四），否则 reloader 会让 systemd 的进程管理变复杂。

---

## 三、远程访问

本机内网 IP 为 `192.168.0.107`。

### 3.1 同局域网直达

浏览器直接开 `http://192.168.0.107:5000`。若打不开，多半是防火墙没放行 5000：

```bash
sudo ufw allow 5000/tcp          # Debian/Ubuntu
sudo firewall-cmd --add-port=5000/tcp --permanent && sudo firewall-cmd --reload  # CentOS/RHEL
```

### 3.2 走 SSH 隧道（最安全，不暴露端口）

在你自己的电脑上执行：

```bash
ssh -L 5000:127.0.0.1:5000 用户名@192.168.0.107
```

然后本地浏览器打开 <http://127.0.0.1:5000>，流量全程走 SSH。

### 3.3 端口映射 / 云主机安全组

若本机是云服务器，需在控制台安全组额外放行 5000（或下节的 80/443）。

---

## 四、生产托管（可选，追求稳定再用）

开发服务器（`app.run`）只适合演示。要更稳，用 WSGI 服务器 + 关调试。

### 4.1 换成 waitress（Windows/Linux 通用）

```bash
.venv/bin/pip install waitress   # 需联网
.venv/bin/waitress-serve --host 0.0.0.0 --port 5000 --call app:app
```

或安装 gunicorn（Linux）：

```bash
.venv/bin/pip install gunicorn
.venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

> 用 WSGI 时依赖 `app:app`；后台 worker 线程在导入 `app.py` 时已随 `start_worker(app)` 启动，可直接工作。

### 4.2 Nginx 反向代理（用 80 端口对外，隐藏 5000）

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 180s;   # 评测较长，避免反代先超时
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

然后把 Flask 只监听本机回环更安全：`app.run(host='127.0.0.1', port=5000)`。

---

## 五、快速自检

服务起来后，用 curl 逐一探活（`--noproxy '*'` 见 §六）：

```bash
for p in / /problems /problems/fwht /standings /help /api/problems /frag/standings; do
  printf '%-20s %s\n' "$p" "$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' http://127.0.0.1:5000$p)"
done
# 期望全部 200
```

---

## 六、常见问题

**Q1. curl / 浏览器访问 `127.0.0.1:5000` 返回 502？**
本机设置了系统代理（`HTTP_PROXY=http://127.0.0.1:7897`），请求被代理拦截。命令行加 `--noproxy '*'`，浏览器把 `127.0.0.1`、`192.168.0.107` 加入"不使用代理"名单即可。

**Q2. 端口 5000 被占用 / 关不掉？**
`debug=True` 会 fork reloader 子进程。查找并清理：

```bash
ss -ltnp | grep :5000          # 找到 PID
kill <PID>; pkill -f "python app.py"
```

**Q3. 页面样式丢失、主题切换无效？**
`base.html` 的 Bootstrap 5 / htmx 走 CDN（`cdn.jsdelivr.net`）。若页面所在网络访问不了 CDN，需自行下载到 `static/` 并改 `base.html` 引用，或保证浏览器能出网。

**Q4. 想换端口？**
改 `app.py` 末行 `port=5000`，或用 WSGI 命令指定 `--port` / `-b 0.0.0.0:新端口`。

**Q5. 提交后一直 `pending`？**
最常见原因是**服务被重启**——任务队列在内存中。启动时 `recover_stale_submissions()` 会把中断的 `pending`/`running` 提交标记为 `runtime_error`，重新提交即可。评测后端见 `evaluator.py` 与 `backends/`（`stub` 桩 / `scratchv_patch` 真实补丁）。纯展示页面不受影响。

---

## 七、停止与清理

```bash
# nohup 方式
kill "$(cat app.pid)"
# systemd 方式
sudo systemctl stop riscv-platform
# 兜底
pkill -f "python app.py"
```

运行时产物（`platform.db`、`submissions/`、`test_data/`、`run.log`）已在 `.gitignore` 中，不会误提交。

---

## 八、命令速查

```bash
# 启动（开发）
.venv/bin/python app.py
# 启动（后台）
nohup .venv/bin/python app.py > run.log 2>&1 & echo $! > app.pid
# 生产
.venv/bin/waitress-serve --host 0.0.0.0 --port 5000 --call app:app
# 访问
http://127.0.0.1:5000
# 停止
kill "$(cat app.pid)"
```
