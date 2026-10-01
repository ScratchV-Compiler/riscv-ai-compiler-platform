#!/bin/sh
# 给指定的人开一个「只能访问平台」的 SSH 隧道账号。
#
#   sh tools/add_tunnel_user.sh zhangsan
#
# 做三件事：
#   1. 建用户 tunnel-<名字>，加入 tunnel 组 —— 该组被 sshd 限制为
#      「只能本地转发、且只能转发到 127.0.0.1:5000」，且不能拿 shell
#   2. 生成一对 ed25519 密钥，公钥装进该账号
#   3. 打印对方的连接命令与私钥位置
#
# 撤销：sh tools/add_tunnel_user.sh --remove zhangsan
set -e

NAME="$1"
[ -n "$NAME" ] || { echo "用法: $0 <名字>   或   $0 --remove <名字>" >&2; exit 1; }

case "$NAME" in
  --remove)
    NAME="$2"
    [ -n "$NAME" ] || { echo "用法: $0 --remove <名字>" >&2; exit 1; }
    U="tunnel-$NAME"
    id "$U" >/dev/null 2>&1 || { echo "账号 $U 不存在"; exit 0; }
    userdel -r "$U" 2>/dev/null || userdel "$U"
    rm -f "/root/tunnel_keys/$NAME" "/root/tunnel_keys/$NAME.pub"
    echo "已撤销：账号 $U 与密钥已删除。对方立即失去访问。"
    exit 0 ;;
esac

# 名字只允许小写字母数字连字符，防注入
echo "$NAME" | grep -Eq '^[a-z0-9][a-z0-9-]{0,30}$' || {
  echo "名字只能是小写字母/数字/连字符（1-31 位）" >&2; exit 1; }

U="tunnel-$NAME"
KEYDIR=/root/tunnel_keys
KEY="$KEYDIR/$NAME"
HOST=$(hostname -I 2>/dev/null | awk '{print $1}')

if id "$U" >/dev/null 2>&1; then
  echo "账号 $U 已存在，只重发密钥。"
else
  useradd -m -s /usr/sbin/nologin -G tunnel "$U"
  echo "已创建账号 $U（shell=nologin，组=tunnel）"
fi

# 密钥：存在就复用，避免每次重跑都换（对方手里的旧私钥会失效）
mkdir -p "$KEYDIR"; chmod 700 "$KEYDIR"
if [ ! -f "$KEY" ]; then
  ssh-keygen -t ed25519 -N '' -C "tunnel-$NAME" -f "$KEY" >/dev/null
  echo "已生成密钥对：$KEY（私钥）/ $KEY.pub"
else
  echo "复用已有密钥：$KEY"
fi

# 装公钥
HOME_DIR=$(getent passwd "$U" | cut -d: -f6)
install -d -m 700 -o "$U" -g "$U" "$HOME_DIR/.ssh"
install -m 600 -o "$U" -g "$U" "$KEY.pub" "$HOME_DIR/.ssh/authorized_keys"

cat <<EOF

────────────────────────────────────────────────────────
私钥**不打印**（会留在终端回滚缓冲与日志里）。
自己去取，并通过可信渠道发给对方：

    cat $KEY

连接命令（保持窗口开着，然后浏览器打开 http://localhost:5000）：

    ssh -i <私钥文件> -N -L 5000:127.0.0.1:5000 ${U}@<服务器公网IP>

    Windows 用 PowerShell / MobaXterm 命令相同。
    必须带 -N —— 该账号 shell 是 nologin，开 shell 会立刻断开。

该账号能做什么：
  ✅ 只能把本地 5000 转发到平台
  ❌ 不能登录 shell、不能转发到别的端口或主机、不能用密码登录
  撤销：sh $0 --remove $NAME
────────────────────────────────────────────────────────
EOF
