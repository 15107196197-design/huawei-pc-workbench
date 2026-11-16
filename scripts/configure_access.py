"""Set the single-operator studio login without putting passwords in shell arguments."""
import getpass
import hashlib
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from huawei_agent.settings import save_settings

username = input("工作台登录名：").strip()
password = getpass.getpass("工作台密码（至少12位，不回显）：")
again = getpass.getpass("再次输入密码：")
if not username or len(password) < 12 or password != again or ":" in username:
    raise SystemExit("登录名、密码长度或两次输入不符合要求，未修改配置")
salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000).hex()
save_settings({"studio_username": username,
               "studio_password_hash": f"pbkdf2_sha256$600000${salt.hex()}${digest}"})
print("登录已配置；只保存加盐哈希，不保存原始密码。公网访问请使用HTTPS。")
