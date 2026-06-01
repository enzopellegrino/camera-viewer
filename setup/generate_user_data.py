#!/usr/bin/env python3
"""
generate_user_data.py — Genera l'user-data per Ubuntu autoinstall
con l'app camera-viewer embedded come base64 in write_files.

Uso:
    python3 generate_user_data.py <camera-viewer.tar.gz> <setup_nuc.sh>
"""
import base64
import sys
import textwrap

if len(sys.argv) < 3:
    print(f"Uso: {sys.argv[0]} <tar.gz> <setup_nuc.sh>", file=sys.stderr)
    sys.exit(1)

tar_path    = sys.argv[1]
setup_path  = sys.argv[2]

# Leggi e codifica il tar.gz in base64
with open(tar_path, 'rb') as f:
    tar_b64 = base64.b64encode(f.read()).decode()

# Spezza in righe da 76 caratteri (standard MIME/YAML)
tar_b64_lines = '\n'.join(
    '          ' + tar_b64[i:i+76]
    for i in range(0, len(tar_b64), 76)
)

# Leggi lo script di setup
with open(setup_path) as f:
    setup_script = f.read()

# Indenta lo script per YAML (8 spazi dentro write_files.content)
setup_indented = '\n'.join(
    '          ' + line if line else ''
    for line in setup_script.splitlines()
)

# Password hash per 'admin' (werkzeug scrypt)
try:
    from werkzeug.security import generate_password_hash
    pw_hash = generate_password_hash('admin')
except ImportError:
    # Fallback: hash bcrypt noto per 'admin' se werkzeug non disponibile
    pw_hash = "pbkdf2:sha256:600000$admin$placeholder"

# Hash OS password N1computer@2019
import subprocess
os_pw_hash = subprocess.check_output(
    ['openssl', 'passwd', '-6', 'N1computer@2019']
).decode().strip()

print(f"""#cloud-config
autoinstall:
  version: 1
  locale: it_IT.UTF-8
  keyboard:
    layout: it
  network:
    network:
      version: 2
      ethernets:
        id0:
          match:
            name: "en*"
          dhcp4: true
  identity:
    hostname: camera-viewer
    realname: pi
    username: pi
    password: "{os_pw_hash}"
  ssh:
    install-server: true
    allow-pw: true
  storage:
    layout:
      name: direct
  packages:
    - curl
    - openssh-server
  late-commands:
    - echo 'pi ALL=(ALL) NOPASSWD:ALL' > /target/etc/sudoers.d/pi
    - chmod 440 /target/etc/sudoers.d/pi

  # Questa sezione viene eseguita da cloud-init al PRIMO AVVIO del sistema.
  # write_files scrive i file prima di runcmd.
  user-data:
    write_files:
      # Archivio app (base64-encoded tar.gz)
      - path: /home/pi/camera-viewer.tar.gz
        encoding: b64
        permissions: '0644'
        owner: root:root
        content: |
{tar_b64_lines}

      # Script di setup (eseguito da runcmd)
      - path: /home/pi/setup-nuc.sh
        permissions: '0755'
        owner: root:root
        content: |
{setup_indented}

    runcmd:
      - [bash, /home/pi/setup-nuc.sh]
""", end='')
