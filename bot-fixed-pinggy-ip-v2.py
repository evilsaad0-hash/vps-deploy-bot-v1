import discord
from discord.ext import commands
import asyncio
import base64
import subprocess
import json
from datetime import datetime, timedelta
import shlex
import logging
import shutil
import os
from typing import Optional, List, Dict, Any
import threading
import time
import sqlite3
import random
import requests
from urllib.parse import urlparse
import string
import secrets
import signal
import re
import xml.etree.ElementTree as ET
import tempfile
import uuid
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
# ─── Container runtime auto-detection ────────────────────────────────────────
def detect_lxc_binary() -> str:
    for candidate in ("incus", "lxc", "lxc-fs"):
        if shutil.which(candidate):
            return candidate
    return "lxc"

def detect_lxd_binary() -> str:
    for candidate in ("incus", "lxd"):
        if shutil.which(candidate):
            return candidate
    return "lxd"

LXC_CMD: str = detect_lxc_binary()
LXD_CMD: str = detect_lxd_binary()

import logging as _logging_tmp
_logging_tmp.getLogger("root").info(f"[Runtime] Container CLI : '{LXC_CMD}'")
_logging_tmp.getLogger("root").info(f"[Runtime] Daemon    CLI : '{LXD_CMD}'")
del _logging_tmp
# ─────────────────────────────────────────────────────────────────────────────

# Load environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
BOT_NAME = os.getenv('BOT_NAME', 'EVM-V3')
PREFIX = os.getenv('BOT_PREFIX', os.getenv('PREFIX', '1')).strip() or '1'

def _normalize_prefix(value: str) -> str:
    """Validate a Discord message-command prefix before storing/using it."""
    value = str(value or '').strip()
    if not value:
        raise ValueError('Prefix cannot be empty.')
    if len(value) > 5:
        raise ValueError('Prefix must be 1-5 characters.')
    if any(ch.isspace() or ch in '`\n\r\t' for ch in value):
        raise ValueError('Prefix cannot contain whitespace or backticks.')
    if value.startswith('<@') or '@everyone' in value or '@here' in value:
        raise ValueError('Mention-style prefixes are not supported.')
    if value.startswith('/'):
        raise ValueError('Slash-command style prefixes are not supported.')
    return value

PREFIX = _normalize_prefix(PREFIX)
YOUR_SERVER_IP = os.getenv('YOUR_SERVER_IP')
MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', '1537063414071828643'))
VPS_USER_ROLE_ID = int(os.getenv('VPS_USER_ROLE_ID', '1553304381623902218'))
DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', 'default')
HOST_MOTD = os.getenv('HOST_MOTD', '')
BOT_VERSION = os.getenv('BOT_VERSION', '22.1-AxionHost-LXC-KVM-Stable')
PROXMOX_WEB_URL = os.getenv('PROXMOX_WEB_URL', '').strip().rstrip('/')
KVM_NETWORK_REPAIR_ON_START = os.getenv('KVM_NETWORK_REPAIR_ON_START', 'true').strip().lower() in ('1','true','yes','on')
KVM_GUEST_NETWORK_TIMEOUT = int(os.getenv('KVM_GUEST_NETWORK_TIMEOUT', '120'))
KVM_QGA_WAIT_TIMEOUT = int(os.getenv('KVM_QGA_WAIT_TIMEOUT', '180'))
KVM_MIN_FREE_MEMORY_GB = float(os.getenv('KVM_MIN_FREE_MEMORY_GB', '1.0'))
KVM_MIN_FREE_DISK_GB = float(os.getenv('KVM_MIN_FREE_DISK_GB', '5.0'))
KVM_BOOT_TIMEOUT = int(os.getenv('KVM_BOOT_TIMEOUT', '90'))
# VoxAI recovery agent state. These names MUST be initialized before the
# background task starts; otherwise discord.py reports a Task exception and
# the manager panel can fail with NameError when it reads the repair state.
AI_AGENT_ENABLED = os.getenv('VOXCLOUD_AI_AGENT_ENABLED', 'true').strip().lower() in ('1','true','yes','on')
try:
    AI_AGENT_INTERVAL = max(30, int(os.getenv('VOXCLOUD_AI_AGENT_INTERVAL', '90')))
except (TypeError, ValueError):
    AI_AGENT_INTERVAL = 90
try:
    AI_AGENT_COOLDOWN = max(120, int(os.getenv('VOXCLOUD_AI_AGENT_COOLDOWN', '600')))
except (TypeError, ValueError):
    AI_AGENT_COOLDOWN = 600
try:
    AI_AGENT_MAX_VPS_PER_CYCLE = max(1, int(os.getenv('VOXCLOUD_AI_AGENT_MAX_VPS_PER_CYCLE', '20')))
except (TypeError, ValueError):
    AI_AGENT_MAX_VPS_PER_CYCLE = 20
_ai_agent_state: Dict[str, Any] = {
    'enabled': AI_AGENT_ENABLED,
    'last_cycle': None,
    'last_actions': [],
    'repairs': 0,
    'errors': 0,
    'healthy': 0,
}
_ai_agent_last_repair: Dict[str, float] = {}
_ai_agent_lock = asyncio.Lock()
BOT_DEVELOPER = os.getenv('BOT_DEVELOPER', 'rehan.404')
BOT_THUMBNAIL_URL = os.getenv('BOT_THUMBNAIL_URL', 'https://cdn.discordapp.com/attachments/1553456349566996520/1557448669694009374/799adf9b-0823-4739-af55-66049200d43f.png?backend=b2&ex=6ac7d69a&is=6ac6851a&hm=fd87bffcac20ca1c1445c8e4b9c6ae27f2cf629d2e4681d84884a7a38a5a8ef4&')
BOT_ICON_URL = os.getenv('BOT_ICON_URL', BOT_THUMBNAIL_URL)
BOT_BANNER_URL = os.getenv('BOT_BANNER_URL', 'https://cdn.discordapp.com/attachments/1553456349566996520/1557448713411100802/file_000000003be882118584bb3106cc0d6d.png?backend=b2&ex=6ac7d6a5&is=6ac68525&hm=ede6ad06007eb039279df2fcb9f1dfb6a534497873254b3063c3b880c1de2804&')

# VPS Expiration Settings
DEFAULT_VPS_EXPIRATION_DAYS = int(os.getenv('DEFAULT_VPS_EXPIRATION_DAYS', '30'))
EXPIRATION_WARNING_DAYS = int(os.getenv('EXPIRATION_WARNING_DAYS', '1'))

# !deploy command — public free deployment is controlled by the persisted admin switch.
# Set these in your .env file:
#   DEPLOY_ROLE_ID=<discord_role_id>   (the member role that can use !deploy)
#   DEPLOY_RAM=4                       (GB of RAM per deployed VPS)
#   DEPLOY_CPU=1                        (CPU cores per deployed VPS)
#   DEPLOY_DISK=30                      (GB disk per deployed VPS)
#   VPS_DEPLOY_LIMIT=1                  (max VPS per user via !deploy — users cannot create more than this)
#   DEPLOY_SLOT=30                       (total global VPS slot cap across ALL users, 0 = unlimited)
DEPLOY_ROLE_ID = int(os.getenv('DEPLOY_ROLE_ID', '0'))
DEPLOY_RAM     = int(os.getenv('DEPLOY_RAM',  '4'))
DEPLOY_CPU     = int(os.getenv('DEPLOY_CPU',  '2'))
DEPLOY_DISK    = int(os.getenv('DEPLOY_DISK', '30'))
# VPS_DEPLOY_LIMIT = max VPS a single user can create via !deploy
# Supports both VPS_DEPLOY_LIMIT (new) and DEPLOY_LIMIT (old) — VPS_DEPLOY_LIMIT takes priority
DEPLOY_LIMIT   = int(os.getenv('VPS_DEPLOY_LIMIT', os.getenv('DEPLOY_LIMIT', '1')))
DEPLOY_SLOT    = int(os.getenv('DEPLOY_SLOT', '0'))
_NODE_SLOT_ENV = next((os.getenv(k) for k in ('NODE_DEFAULT_SLOTS', 'NODE_SLOTS', 'NODE_CAPACITY', 'NODE_TOTAL_VPS') if os.getenv(k) is not None), None)
NODE_DEFAULT_SLOTS = max(1, int(_NODE_SLOT_ENV or '100'))
# Security baseline: nesting/Docker support is enabled by default; privileged mode remains opt-in because it weakens container isolation.
VPS_PRIVILEGED = os.getenv('VPS_PRIVILEGED', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
VPS_NESTING = os.getenv('VPS_NESTING', 'true').strip().lower() in ('1', 'true', 'yes', 'on')
VPS_HARDEN_SSH = os.getenv('VPS_HARDEN_SSH', 'true').strip().lower() in ('1', 'true', 'yes', 'on')
# Public free deployment is allowed only when the persisted admin switch is enabled.
ADMIN_ONLY_DEPLOY = False

# Virtualization / performance settings
# KVM provisioning is intentionally disabled in this build; LXC remains available.
KVM_ENABLED = False
KVM_IMAGE_DIR = os.getenv('KVM_IMAGE_DIR', '/var/lib/libvirt/images/voxelcloud')
KVM_NETWORK = os.getenv('KVM_NETWORK', 'default')
KVM_CPU_MODE = os.getenv('KVM_CPU_MODE', 'auto').strip() or 'auto'
# Docker-in-LXC support: nesting is enabled by default and new LXC guests are prepared for nested Docker workloads.
VPS_DOCKER_READY = os.getenv('VPS_DOCKER_READY', 'true').strip().lower() in ('1', 'true', 'yes', 'on')
VPS_DOCKER_KERNEL_MODULES = os.getenv('VPS_DOCKER_KERNEL_MODULES', 'overlay,br_netfilter').strip()
KVM_AUTOSTART = os.getenv('KVM_AUTOSTART', 'true').strip().lower() in ('1', 'true', 'yes', 'on')
# Automatically recover from a stale/incompatible named CPU selection by using
# a host-compatible CPU mode. The actual CPU mode is stored/reported, so the
# guest never claims to have a CPU model that the host cannot provide.
KVM_CPU_AUTO_FALLBACK = os.getenv('KVM_CPU_AUTO_FALLBACK', 'true').strip().lower() in ('1', 'true', 'yes', 'on')
# Optional platform integrations
CLOUDFLARE_TUNNEL_TOKEN = os.getenv('CLOUDFLARE_TUNNEL_TOKEN', '').strip()
CLOUDFLARE_INSTALL_ENABLED = os.getenv('CLOUDFLARE_INSTALL_ENABLED', 'true').strip().lower() in ('1','true','yes','on')
KVM_PINGGY_ENABLED = os.getenv('KVM_PINGGY_ENABLED', 'true').strip().lower() in ('1','true','yes','on')
# Reliability controls
PTERO_PANEL_URL = os.getenv('PTERO_PANEL_URL', '').strip().rstrip('/')
PTERO_API_KEY = os.getenv('PTERO_API_KEY', '').strip()
PTERO_DEFAULT_NEST_ID = int(os.getenv('PTERO_DEFAULT_NEST_ID', '1'))
PTERO_DEFAULT_EGG_ID = int(os.getenv('PTERO_DEFAULT_EGG_ID', '1'))
PTERO_DEFAULT_ALLOCATION_ID = int(os.getenv('PTERO_DEFAULT_ALLOCATION_ID', '1'))
# KVM uses official cloud/generic images.  Every OS exposed by OS_OPTIONS is
# intentionally available to KVM too; Alpine entries use the release directory
# and are resolved to the newest x86_64 cloud-init QCOW2 automatically.
KVM_SUPPORTED_IMAGES = {
    'ubuntu:20.04': {'url': 'https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img', 'variant': 'ubuntu20.04'},
    'ubuntu:22.04': {'url': 'https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img', 'variant': 'ubuntu22.04'},
    'ubuntu:24.04': {'url': 'https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img', 'variant': 'ubuntu24.04'},
    'ubuntu:25.10': {'url': 'https://cloud-images.ubuntu.com/questing/current/questing-server-cloudimg-amd64.img', 'variant': 'ubuntu25.10'},
    'ubuntu:26.04': {'url': 'https://cloud-images.ubuntu.com/resolute/current/resolute-server-cloudimg-amd64.img', 'variant': 'ubuntu26.04'},
    'images:debian/11': {'url': 'https://cloud.debian.org/images/cloud/bullseye/latest/debian-11-genericcloud-amd64.qcow2', 'variant': 'debian11'},
    'images:debian/12': {'url': 'https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2', 'variant': 'debian12'},
    'images:debian/13': {'url': 'https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2', 'variant': 'debian13'},
    'images:alpine/3.20': {'url': 'https://dev.alpinelinux.org/~tomalok/alpine-cloud-images/v3.20/generic/x86_64/alpine-3.20.8-x86_64-bios-cloudinit-r0.qcow2', 'variant': 'alpine3.20'},
    'images:alpine/3.21': {'url': 'https://dev.alpinelinux.org/~tomalok/alpine-cloud-images/v3.21/generic/x86_64/alpine-3.21.8-x86_64-bios-cloudinit-r0.qcow2', 'variant': 'alpine3.21'},
    'images:rockylinux/9': {'url': 'https://dl.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud.latest.x86_64.qcow2', 'variant': 'rocky9'},
    'images:almalinux/9': {'url': 'https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/AlmaLinux-9-GenericCloud-latest.x86_64.qcow2', 'variant': 'almalinux9'},
    'images:opensuse/15.6': {'url': 'https://download-repositories.opensuse.org/download/repositories/Cloud:/Images:/Leap_15.6/images/openSUSE-Leap-15.6.x86_64-NoCloud.qcow2', 'variant': 'opensuse15.6'},
    'images:centos/9-Stream': {'url': 'https://cloud.centos.org/centos/9-stream/x86_64/images/CentOS-Stream-GenericCloud-9-latest.x86_64.qcow2', 'variant': 'centos-stream9'},
}

# SSH Configuration
SSH_FIX_SCRIPT = """#!/bin/bash
cat > /etc/ssh/sshd_config << 'SSHEOF'
Port 22
AddressFamily any
ListenAddress 0.0.0.0
ListenAddress ::
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin yes
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM yes
MaxAuthTries 6
MaxSessions 10
SyslogFacility AUTH
LogLevel INFO
X11Forwarding yes
X11DisplayOffset 10
PrintMotd no
PrintLastLog yes
TCPKeepAlive yes
PermitUserEnvironment no
Subsystem sftp /usr/lib/openssh/sftp-server
SSHEOF
systemctl restart ssh 2>/dev/null || service ssh restart 2>/dev/null || /etc/init.d/ssh restart 2>/dev/null || true
"""

# OS Options for VPS Creation and Reinstall
OS_OPTIONS = [
    {"label": "Ubuntu 20.04 LTS", "value": "ubuntu:20.04"},
    {"label": "Ubuntu 22.04 LTS", "value": "ubuntu:22.04"},
    {"label": "Ubuntu 24.04 LTS", "value": "ubuntu:24.04"},
    {"label": "Ubuntu 25.10", "value": "ubuntu:25.10"},
    {"label": "Ubuntu 26.04 LTS (Latest)", "value": "ubuntu:26.04"},
    {"label": "Debian 11 (Bullseye)", "value": "images:debian/11"},
    {"label": "Debian 12 (Bookworm)", "value": "images:debian/12"},
    {"label": "Debian 13 (Trixie)", "value": "images:debian/13"},
    {"label": "Alpine 3.20", "value": "images:alpine/3.20"},
    {"label": "Alpine 3.21", "value": "images:alpine/3.21"},
    {"label": "Rocky Linux 9", "value": "images:rockylinux/9"},
    {"label": "AlmaLinux 9", "value": "images:almalinux/9"},
    {"label": "openSUSE Leap 15.6", "value": "images:opensuse/15.6"},
    {"label": "CentOS Stream 9", "value": "images:centos/9-Stream"},
]


# -----------------------------------------------------------------------------
# Runtime-safe image/storage helpers
# -----------------------------------------------------------------------------
def _normalise_image_ref(image_ref: str) -> str:
    """Normalize a user/UI OS value into a safe Incus/LXC image reference."""
    image_ref = (image_ref or "").strip()
    if not image_ref:
        raise ValueError("No OS image was selected.")
    # Only allow image-server style refs from the configured OS list. This also
    # prevents command injection because execute_lxc ultimately shell-splits.
    allowed = {o["value"] for o in OS_OPTIONS}
    if image_ref not in allowed:
        raise ValueError(f"Unsupported OS image: {image_ref}")
    return image_ref

async def _ensure_lxc_images_remote(node_id: int) -> str:
    """Ensure a dedicated Linux Containers image remote exists without changing a user's existing `images:` remote."""
    remote_name = "voxel-images"
    try:
        await execute_lxc("", f"remote get-url {remote_name}", node_id=node_id, timeout=20)
        return remote_name
    except Exception:
        pass

    try:
        await execute_lxc(
            "",
            f"remote add {remote_name} https://images.linuxcontainers.org --protocol=simplestreams --public",
            node_id=node_id,
            timeout=60,
        )
        return remote_name
    except Exception as exc:
        logger.warning("Could not configure fallback image remote on node %s: %s", node_id, exc)
        return ""

async def validate_os_image(image_ref: str, node_id: int) -> str:
    """Resolve the selected OS to an image reference that actually works on the target LXD node."""
    image_ref = _normalise_image_ref(image_ref)

    # Canonical's official Ubuntu remote is the most reliable source for Ubuntu
    # container images on LXD. Keep the old `images:` value as a fallback so old
    # installations continue to work.
    candidates = [image_ref]
    if image_ref.startswith("images:ubuntu/"):
        version = image_ref.rsplit("/", 1)[-1]
        candidates = [f"ubuntu:{version}", image_ref]
    elif image_ref.startswith("ubuntu:"):
        version = image_ref.split(":", 1)[1]
        candidates = [image_ref, f"images:ubuntu/{version}"]

    # If the configured images: remote is unavailable for Debian (or another
    # image), add a separate fallback remote instead of overwriting the user's
    # existing remote configuration.
    if image_ref.startswith("images:"):
        alias = image_ref.split(":", 1)[1]
        candidates.append(f"voxel-images:{alias}")

    errors = []
    attempted = set()
    for candidate in candidates:
        if candidate in attempted:
            continue
        attempted.add(candidate)
        try:
            await execute_lxc("", f"image info {shlex.quote(candidate)}", node_id=node_id, timeout=45)
            if candidate.startswith("voxel-images:"):
                logger.info("Using fallback image remote for node %s: %s", node_id, candidate)
            elif candidate != image_ref:
                logger.info("Using image fallback on node %s: %s (selected %s)", node_id, candidate, image_ref)
            return candidate
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")

        if candidate.startswith("voxel-images:"):
            # The remote may not exist yet; create it and retry once.
            remote = await _ensure_lxc_images_remote(node_id)
            if remote:
                try:
                    await execute_lxc("", f"image info {shlex.quote(remote + ':' + alias)}", node_id=node_id, timeout=45)
                    return remote + ":" + alias
                except Exception as exc:
                    errors.append(f"{remote}:{alias}: {exc}")

    details = " | ".join(errors[-3:])
    raise RuntimeError(
        f"No usable OS image was found for `{image_ref}` on node {node_id}. "
        f"Tried the configured image and safe fallbacks. Details: {details}"
    )

async def resolve_storage_pool(node_id: int) -> str:
    """Return a storage pool that actually exists on the target node."""
    preferred = (DEFAULT_STORAGE_POOL or "").strip()
    try:
        raw = await execute_lxc("", "storage list --format csv", node_id=node_id, timeout=30)
        names = []
        for line in str(raw or "").splitlines():
            line = line.strip()
            if not line:
                continue
            first = line.split(",", 1)[0].strip().strip('"')
            if first and first.lower() not in {"name", "storage pool"}:
                names.append(first)
        if preferred and preferred in names:
            return preferred
        if names:
            logger.warning("Configured storage pool %r is unavailable on node %s; using %r", preferred, node_id, names[0])
            return names[0]
    except Exception as exc:
        logger.warning("Could not query storage pools on node %s: %s", node_id, exc)
    # Keep backward compatibility with existing installations. The init call
    # will return the exact daemon error if no such pool exists.
    return preferred or "default"

async def create_instance_from_image(container_name: str, image_ref: str, node_id: int, storage_pool: str = None):
    """Create an instance with validated image/pool and useful diagnostics."""
    image_ref = await validate_os_image(image_ref, node_id)
    pool = storage_pool or await resolve_storage_pool(node_id)
    command = (
        f"init {shlex.quote(image_ref)} {shlex.quote(container_name)} "
        f"-s {shlex.quote(pool)} -c security.privileged={'true' if VPS_PRIVILEGED else 'false'}"
    )
    try:
        await execute_lxc(container_name, command, node_id=node_id, timeout=180)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to create `{container_name}` from `{image_ref}` using storage pool `{pool}`. "
            f"Check the node's storage pool and image remote. Details: {exc}"
        ) from exc
    return image_ref, pool

async def safe_delete_instance(container_name: str, node_id: int):
    """Delete an instance if it exists; tolerate an already-absent container."""
    try:
        await execute_lxc(container_name, f"delete {shlex.quote(container_name)} --force", node_id=node_id, timeout=120)
    except Exception as exc:
        msg = str(exc).lower()
        if any(x in msg for x in ("not found", "does not exist", "no such instance", "not exist")):
            return
        raise


def is_admin_user_id(user_id: str) -> bool:
    """Return True for the main admin or an admin stored in the admins table."""
    uid = str(user_id)
    return uid == str(MAIN_ADMIN_ID) or uid in {str(x) for x in admin_data.get("admins", [])}


def is_free_deploy_enabled() -> bool:
    """Read the persisted public free-deploy switch (disabled by default)."""
    return str(get_setting('free_deploy_enabled', '0')).strip().lower() in ('1', 'true', 'yes', 'on', 'enabled')


def get_free_deploy_config() -> Dict[str, int]:
    """Read persisted free-deploy settings; database values survive restarts."""
    defaults = {'ram': DEPLOY_RAM, 'cpu': DEPLOY_CPU, 'disk': DEPLOY_DISK, 'user_limit': DEPLOY_LIMIT}
    result: Dict[str, int] = {}
    for key, default in defaults.items():
        try:
            result[key] = max(0, int(get_setting(f'free_deploy_{key}', str(default))))
        except (TypeError, ValueError):
            result[key] = default
    return result


async def lxc_instance_exists(container_name: str, node_id: int) -> bool:
    """Check the target node for an exact instance-name collision."""
    try:
        raw = await execute_lxc("", "list --format csv -c n", node_id=node_id, timeout=30)
        wanted = container_name.strip()
        for line in str(raw or "").splitlines():
            name = line.strip().strip('"').split(",", 1)[0].strip().strip('"')
            if name == wanted:
                return True
        return False
    except Exception as exc:
        # Never treat a failed LXD query as a free name. In nested/loaded nodes,
        # Go/LXD may temporarily fail to create a pthread with EAGAIN; retry the
        # read-only existence check before returning a hard deployment failure.
        msg = str(exc)
        low = msg.lower()
        if any(x in low for x in ('pthread_create failed', 'resource temporarily unavailable', 'cannot determine seccomp compiler version', 'eagain')):
            for attempt, delay in enumerate((1.0, 2.0, 4.0), 1):
                await asyncio.sleep(delay)
                try:
                    raw = await execute_lxc("", "list --format csv -c n", node_id=node_id, timeout=30)
                    wanted = container_name.strip()
                    names = {line.strip().strip('\"').split(',', 1)[0].strip().strip('\"') for line in str(raw or '').splitlines()}
                    return wanted in names
                except Exception as retry_exc:
                    logger.warning("LXC name check retry %d/3 failed for %r on node %s: %s", attempt, container_name, node_id, retry_exc)
            raise RuntimeError(
                f"Node {node_id} is resource-exhausted while LXD checks VPS names (pthread/process limit). "
                f"Free host resources or increase the node's PID/TasksMax/NPROC limits, then retry. Original error: {msg}"
            ) from exc
        logger.warning("Could not check LXC name %r on node %s: %s", container_name, node_id, exc)
        raise RuntimeError(f"Could not verify whether VPS name `{container_name}` is already in use on node {node_id}: {exc}") from exc


async def allocate_unique_container_name(username: str, node_id: int) -> tuple[str, int]:
    """Allocate a VPS name that is unique in both SQLite and the real LXC node.

    The old MAX(id)+1 naming scheme could reuse an ID when a previous deployment
    created an LXC instance but failed before the database save. This helper checks
    both sources and skips any stale/existing name instead of failing with
    `Instance ... already exists`.
    """
    sanitized = sanitize_username_for_container(str(username).lower()[:30])
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM vps")
        next_id = int(cur.fetchone()[0] or 0) + 1
    finally:
        conn.close()

    for _ in range(10000):
        candidate = f"{sanitized}-vps-{next_id}"
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM vps WHERE container_name = ? LIMIT 1", (candidate,))
            db_exists = cur.fetchone() is not None
        finally:
            conn.close()

        if not db_exists and not await lxc_instance_exists(candidate, node_id):
            return candidate, next_id
        next_id += 1

    raise RuntimeError(f"Could not allocate a unique VPS name for `{sanitized}` on node {node_id}.")


# Configure logging to file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(f'{BOT_NAME.lower()}_vps_bot')


async def http_request(method: str, url: str, **kwargs):
    return await asyncio.to_thread(requests.request, method, url, **kwargs)


def run_on_bot_loop(coro, timeout=120):
    """Run a coroutine on Discord's existing event loop from a worker thread."""
    loop = bot.loop
    if not loop.is_running():
        raise RuntimeError("Discord event loop is not running")
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)

# Database setup
# Keep the VPS database tied to the bot source directory instead of the process
# working directory. A restart through systemd/screen/pm2/docker can use a
# different CWD; a relative `vps.db` would otherwise create a new empty DB and
# make all VPS appear to have disappeared.
BOT_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB_PATH = os.path.join(BOT_BASE_DIR, 'vps.db')
DB_PATH = os.path.abspath(os.getenv('VPS_DB_PATH', _DEFAULT_DB_PATH))

# One-time compatibility migration for older installs that kept vps.db in the
# current working directory. Never overwrite an existing persistent database.
if not os.getenv('VPS_DB_PATH'):
    _legacy_db = os.path.abspath(os.path.join(os.getcwd(), 'vps.db'))
    if _legacy_db != DB_PATH and os.path.exists(_legacy_db) and not os.path.exists(DB_PATH):
        try:
            shutil.copy2(_legacy_db, DB_PATH)
            for _suffix in ('-wal', '-shm'):
                _src = _legacy_db + _suffix
                _dst = DB_PATH + _suffix
                if os.path.exists(_src):
                    shutil.copy2(_src, _dst)
            logging.getLogger(__name__).warning(
                'Migrated legacy VPS database from %s to %s', _legacy_db, DB_PATH
            )
        except Exception as _db_migration_error:
            logging.getLogger(__name__).error(
                'Could not migrate legacy VPS database: %s', _db_migration_error
            )

def get_db():
    # Always use the same absolute database path across bot restarts.
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id TEXT PRIMARY KEY
    )''')
    cur.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (str(MAIN_ADMIN_ID),))
    cur.execute('''CREATE TABLE IF NOT EXISTS nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        location TEXT,
        total_vps INTEGER,
        tags TEXT DEFAULT '[]',
        api_key TEXT,
        url TEXT,
        is_local INTEGER DEFAULT 0
    )''')
    # Add local node if not exists
    cur.execute('SELECT COUNT(*) FROM nodes WHERE is_local = 1')
    if cur.fetchone()[0] == 0:
        cur.execute('INSERT INTO nodes (name, location, total_vps, tags, api_key, url, is_local) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    ('Local Node', 'Local', NODE_DEFAULT_SLOTS, '[]', None, None, 1))  # Configurable default capacity
    elif _NODE_SLOT_ENV is not None:
        cur.execute('UPDATE nodes SET total_vps=? WHERE id=(SELECT id FROM nodes WHERE is_local=1 ORDER BY id LIMIT 1)', (NODE_DEFAULT_SLOTS,))
    cur.execute('''CREATE TABLE IF NOT EXISTS vps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        node_id INTEGER NOT NULL DEFAULT 1,
        container_name TEXT UNIQUE NOT NULL,
        ram TEXT NOT NULL,
        cpu TEXT NOT NULL,
        storage TEXT NOT NULL,
        config TEXT NOT NULL,
        os_version TEXT DEFAULT 'ubuntu:22.04',
        status TEXT DEFAULT 'stopped',
        suspended INTEGER DEFAULT 0,
        whitelisted INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        shared_with TEXT DEFAULT '[]',
        suspension_history TEXT DEFAULT '[]',
        expiration_date TEXT DEFAULT NULL,
        root_password TEXT DEFAULT NULL
    )''')
    # Migrations
    cur.execute('PRAGMA table_info(vps)')
    info = cur.fetchall()
    columns = [col[1] for col in info]
    if 'os_version' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN os_version TEXT DEFAULT 'ubuntu:22.04'")
    if 'node_id' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN node_id INTEGER DEFAULT 1")
    if 'expiration_date' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN expiration_date TEXT DEFAULT NULL")
    if 'root_password' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN root_password TEXT DEFAULT NULL")
    if 'backend' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN backend TEXT DEFAULT 'lxc'")
    if 'cpu_model' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN cpu_model TEXT DEFAULT NULL")
    if 'provision_source' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN provision_source TEXT DEFAULT 'admin'")
    if 'reward_tier' not in columns:
        cur.execute("ALTER TABLE vps ADD COLUMN reward_tier INTEGER DEFAULT NULL")
    cur.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')
    settings_init = [
        ('cpu_threshold', '90'),
        ('ram_threshold', '90'),
        # Persist the deployment/default node in SQLite so it survives restarts.
        # Normal mode uses the local controller; remote-only mode requires a remote node.
        ('default_node_id', '0'),
    ]
    for key, value in settings_init:
        cur.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
    cur.execute('''CREATE TABLE IF NOT EXISTS port_allocations (
        user_id TEXT PRIMARY KEY,
        allocated_ports INTEGER DEFAULT 0
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS port_forwards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        vps_container TEXT NOT NULL,
        vps_port INTEGER NOT NULL,
        host_port INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )''')
    # Invite VPS rewards and referral tracking.
    cur.execute('''CREATE TABLE IF NOT EXISTS invite_rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        min_invites INTEGER NOT NULL UNIQUE,
        ram_gb INTEGER NOT NULL,
        cpu_cores INTEGER NOT NULL,
        disk_gb INTEGER NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS invite_referrals (
        guild_id TEXT NOT NULL,
        inviter_id TEXT NOT NULL,
        invitee_id TEXT NOT NULL,
        invite_code TEXT,
        joined_at TEXT NOT NULL,
        left_at TEXT DEFAULT NULL,
        PRIMARY KEY (guild_id, invitee_id)
    )''')
    cur.execute('''CREATE INDEX IF NOT EXISTS idx_invite_referrals_valid
                   ON invite_referrals(guild_id, inviter_id, left_at)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS invite_claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        min_invites INTEGER NOT NULL,
        reward_id INTEGER,
        status TEXT NOT NULL DEFAULT 'pending',
        invite_count INTEGER NOT NULL DEFAULT 0,
        ram_gb INTEGER NOT NULL,
        cpu_cores INTEGER NOT NULL,
        disk_gb INTEGER NOT NULL,
        vps_id INTEGER DEFAULT NULL,
        container_name TEXT DEFAULT NULL,
        claimed_at TEXT DEFAULT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(guild_id, user_id, min_invites)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS invite_cache (
        guild_id TEXT NOT NULL,
        invite_code TEXT NOT NULL,
        inviter_id TEXT,
        uses INTEGER NOT NULL DEFAULT 0,
        max_uses INTEGER NOT NULL DEFAULT 0,
        channel_id TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (guild_id, invite_code)
    )''')
    default_rewards = [
        (2, 4, 2, 20, '4GB Invite VPS'),
        (4, 8, 4, 35, '8GB Invite VPS'),
        (8, 16, 6, 40, '16GB Invite VPS'),
        (16, 32, 8, 80, '32GB Invite VPS'),
    ]
    now_iso = datetime.now().isoformat()
    for _min, _ram, _cpu, _disk, _name in default_rewards:
        cur.execute(
            '''INSERT OR IGNORE INTO invite_rewards
               (min_invites, ram_gb, cpu_cores, disk_gb, name, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)''',
            (_min, _ram, _cpu, _disk, _name, now_iso, now_iso)
        )
    # Schema migrations for features added after the original VPS schema.
    # These are deliberately additive: existing VPS rows, IDs and passwords are preserved.
    cur.execute('PRAGMA table_info(vps)')
    _vps_cols = {str(row[1]) for row in cur.fetchall()}
    _vps_extra_columns = {
        'bandwidth_gb': 'REAL DEFAULT 0',
        'bandwidth_used_bytes': 'INTEGER DEFAULT 0',
        'bandwidth_cycle_start': 'TEXT DEFAULT NULL',
        'bandwidth_last_rx_bytes': 'INTEGER DEFAULT 0',
        'bandwidth_last_tx_bytes': 'INTEGER DEFAULT 0',
        'bandwidth_last_sample_at': 'TEXT DEFAULT NULL',
        'last_modified': 'TEXT DEFAULT CURRENT_TIMESTAMP',
    }
    for _name, _definition in _vps_extra_columns.items():
        if _name not in _vps_cols:
            try:
                cur.execute(f'ALTER TABLE vps ADD COLUMN {_name} {_definition}')
            except sqlite3.OperationalError as _exc:
                # SQLite rejects CURRENT_TIMESTAMP as a non-constant ADD COLUMN default.
                if _name == 'last_modified':
                    cur.execute('ALTER TABLE vps ADD COLUMN last_modified TEXT DEFAULT NULL')
                else:
                    raise

    # New audit/logging table. Older databases did not have it, which caused
    # repeated `no such table: audit_logs` warnings every time the health logger ran.
    cur.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL DEFAULT 'system',
        action TEXT NOT NULL,
        detail TEXT DEFAULT '',
        user_id TEXT,
        node_id INTEGER,
        vps_container TEXT,
        created_at TEXT NOT NULL
    )''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(id DESC)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_vps ON audit_logs(vps_container, id DESC)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_node ON audit_logs(node_id, id DESC)')

    # Newer slot accounting code stores a modification timestamp.
    cur.execute('PRAGMA table_info(port_allocations)')
    _port_cols = {str(row[1]) for row in cur.fetchall()}
    if 'last_modified' not in _port_cols:
        cur.execute('ALTER TABLE port_allocations ADD COLUMN last_modified TEXT DEFAULT NULL')

    conn.commit()
    conn.close()

def get_setting(key: str, default: Any = None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def get_nodes() -> List[Dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM nodes')
    rows = cur.fetchall()
    conn.close()
    nodes = [dict(row) for row in rows]
    for node in nodes:
        
        try:
            node['tags'] = json.loads(node.get('tags') or '[]')
        except (TypeError, json.JSONDecodeError):
            node['tags'] = []
        # Ensure is_local is properly converted
        node['is_local'] = int(node.get('is_local', 1)) == 1
    return nodes

def get_node(node_id: int) -> Optional[Dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM nodes WHERE id = ?', (node_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        node = dict(row)
        
        try:
            node['tags'] = json.loads(node.get('tags') or '[]')
        except (TypeError, json.JSONDecodeError):
            node['tags'] = []
        # Ensure is_local is properly converted
        node['is_local'] = int(node.get('is_local', 1)) == 1
        return node
    return None

def get_vps_by_id(vps_id: int) -> Optional[Dict]:
    """Get VPS info by global VPS ID"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM vps WHERE id = ?', (vps_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        vps = dict(row)
        try:
            vps['shared_with'] = json.loads(vps.get('shared_with', '[]') or '[]')
        except (TypeError, json.JSONDecodeError):
            vps['shared_with'] = []
        try:
            vps['suspension_history'] = json.loads(vps.get('suspension_history', '[]') or '[]')
        except (TypeError, json.JSONDecodeError):
            vps['suspension_history'] = []
        vps['suspended'] = bool(vps.get('suspended', 0))
        vps['whitelisted'] = bool(vps.get('whitelisted', 0))
        vps['os_version'] = vps.get('os_version', 'ubuntu:22.04')
        vps['backend'] = vps.get('backend') or 'lxc'
        vps['cpu_model'] = vps.get('cpu_model') or None
        return vps
    return None

def resolve_vps_reference(vps_ref: str) -> Optional[Dict]:
    """Resolve a VPS by numeric DB id OR by its container/VPS name.

    This keeps commands user-friendly: both `123` and `myuser-vps-1` are accepted.
    Matching is exact and case-insensitive for names.
    """
    ref = str(vps_ref or '').strip()
    if not ref:
        return None
    if ref.isdigit():
        return get_vps_by_id(int(ref))
    conn = get_db()
    try:
        row = conn.execute(
            'SELECT * FROM vps WHERE lower(container_name) = lower(?) LIMIT 1',
            (ref,)
        ).fetchone()
        if not row:
            return None
        vps = dict(row)
        try:
            vps['shared_with'] = json.loads(vps.get('shared_with', '[]') or '[]')
        except (TypeError, json.JSONDecodeError):
            vps['shared_with'] = []
        try:
            vps['suspension_history'] = json.loads(vps.get('suspension_history', '[]') or '[]')
        except (TypeError, json.JSONDecodeError):
            vps['suspension_history'] = []
        vps['suspended'] = bool(vps.get('suspended', 0))
        vps['whitelisted'] = bool(vps.get('whitelisted', 0))
        vps['os_version'] = vps.get('os_version', 'ubuntu:22.04')
        vps['backend'] = vps.get('backend') or 'lxc'
        vps['cpu_model'] = vps.get('cpu_model') or None
        return vps
    finally:
        conn.close()


def get_current_vps_count(node_id: int) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM vps WHERE node_id = ?', (node_id,))
    count = cur.fetchone()[0]
    conn.close()
    return count

def get_vps_data() -> Dict[str, List[Dict[str, Any]]]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM vps')
    rows = cur.fetchall()
    conn.close()
    data = {}
    for row in rows:
        user_id = row['user_id']
        if user_id not in data:
            data[user_id] = []
        vps = dict(row)
        try:
            vps['shared_with'] = json.loads(vps.get('shared_with') or '[]')
        except (TypeError, json.JSONDecodeError):
            vps['shared_with'] = []
        try:
            vps['suspension_history'] = json.loads(vps.get('suspension_history') or '[]')
        except (TypeError, json.JSONDecodeError):
            vps['suspension_history'] = []
        vps['suspended'] = bool(vps['suspended'])
        vps['whitelisted'] = bool(vps['whitelisted'])
        vps['os_version'] = vps.get('os_version', 'ubuntu:22.04')
        vps['backend'] = vps.get('backend') or 'lxc'
        vps['cpu_model'] = vps.get('cpu_model') or None
        vps['provision_source'] = vps.get('provision_source') or 'admin'
        vps['reward_tier'] = vps.get('reward_tier')
        data[user_id].append(vps)
    return data

def get_admins() -> List[str]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT user_id FROM admins')
    rows = cur.fetchall()
    conn.close()
    return [row['user_id'] for row in rows]

def save_vps_data():
    """Persist all in-memory VPS records safely and permanently.

    The old implementation treated any in-memory ``id`` as an existing SQLite
    row and only ran UPDATE. If that ID was stale or collided, SQLite updated
    zero rows and the bot still reported success; after restart the VPS was
    gone from the panel. This version verifies the ID, falls back to the unique
    container name, and INSERTs when the row does not exist.
    """
    if not vps_data:
        return

    conn = get_db()
    cur = conn.cursor()
    try:
        for user_id, vps_list in list(vps_data.items()):
            for vps in list(vps_list):
                container_name = str(vps.get('container_name') or '').strip()
                if not container_name:
                    logger.warning('Skipping VPS record without container_name for user %s', user_id)
                    continue

                shared_json = json.dumps(vps.get('shared_with', []))
                history_json = json.dumps(vps.get('suspension_history', []))
                suspended_int = 1 if vps.get('suspended') else 0
                whitelisted_int = 1 if vps.get('whitelisted', False) else 0
                os_ver = vps.get('os_version', 'ubuntu:22.04')
                created_at = vps.get('created_at', datetime.now().isoformat())
                node_id = vps.get('node_id', 1)
                expiration_date = vps.get('expiration_date')
                root_password = vps.get('root_password')
                backend = vps.get('backend', 'lxc') or 'lxc'
                cpu_model = vps.get('cpu_model')
                provision_source = vps.get('provision_source', 'admin') or 'admin'
                reward_tier = vps.get('reward_tier')
                status = vps.get('status', 'stopped')
                vps_id = vps.get('id')

                existing_id = None
                if vps_id is not None:
                    cur.execute('SELECT id, container_name FROM vps WHERE id = ?', (vps_id,))
                    row = cur.fetchone()
                    if row and row['container_name'] == container_name:
                        existing_id = int(row['id'])
                    elif row:
                        logger.warning(
                            'VPS ID collision: memory id=%s belongs to %s, current container=%s; resolving by container name.',
                            vps_id, row['container_name'], container_name
                        )

                # container_name is UNIQUE and is the safest identity.
                if existing_id is None:
                    cur.execute('SELECT id FROM vps WHERE container_name = ?', (container_name,))
                    row = cur.fetchone()
                    if row:
                        existing_id = int(row['id'])

                values = (
                    str(user_id), node_id, container_name, vps.get('ram', '0GB'),
                    vps.get('cpu', '0'), vps.get('storage', '0GB'),
                    vps.get('config', ''), os_ver, status, suspended_int,
                    whitelisted_int, created_at, shared_json, history_json,
                    expiration_date, root_password, backend, cpu_model,
                    provision_source, reward_tier
                )

                if existing_id is not None:
                    cur.execute(
                        '''UPDATE vps SET user_id=?, node_id=?, container_name=?, ram=?, cpu=?,
                           storage=?, config=?, os_version=?, status=?, suspended=?,
                           whitelisted=?, created_at=?, shared_with=?, suspension_history=?,
                           expiration_date=?, root_password=?, backend=?, cpu_model=?,
                           provision_source=?, reward_tier=? WHERE id=?''',
                        values + (existing_id,)
                    )
                    vps['id'] = existing_id
                else:
                    cur.execute(
                        '''INSERT INTO vps
                           (user_id, node_id, container_name, ram, cpu, storage, config,
                            os_version, status, suspended, whitelisted, created_at,
                            shared_with, suspension_history, expiration_date, root_password, backend, cpu_model,
                            provision_source, reward_tier)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        values
                    )
                    vps['id'] = cur.lastrowid

        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception('Failed to persist VPS data to %s', DB_PATH)
        raise
    finally:
        conn.close()

def save_admin_data():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM admins')
    for admin_id in admin_data['admins']:
        cur.execute('INSERT INTO admins (user_id) VALUES (?)', (admin_id,))
    conn.commit()
    conn.close()

# Port forwarding functions
def get_user_allocation(user_id: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT allocated_ports FROM port_allocations WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0

def get_user_used_ports(user_id: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM port_forwards WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0]

def allocate_ports(user_id: str, amount: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO port_allocations (user_id, allocated_ports) VALUES (?, COALESCE((SELECT allocated_ports FROM port_allocations WHERE user_id = ?), 0) + ?)', (user_id, user_id, amount))
    conn.commit()
    conn.close()

def deallocate_ports(user_id: str, amount: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('UPDATE port_allocations SET allocated_ports = MAX(0, allocated_ports - ?) WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def get_available_host_port(node_id: int) -> Optional[int]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT host_port FROM port_forwards WHERE vps_container IN (SELECT container_name FROM vps WHERE node_id = ?)', (node_id,))
    used_ports = set(row[0] for row in cur.fetchall())
    conn.close()
    for _ in range(100):
        port = random.randint(20000, 50000)
        if port not in used_ports:
            return port
    return None

async def create_port_forward(user_id: str, container: str, vps_port: int, node_id: int) -> Optional[int]:
    host_port = get_available_host_port(node_id)
    if not host_port:
        return None
    try:
        await execute_lxc(container, f"config device add {container} tcp_proxy_{host_port} proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:{vps_port}", node_id=node_id)
        await execute_lxc(container, f"config device add {container} udp_proxy_{host_port} proxy listen=udp:0.0.0.0:{host_port} connect=udp:127.0.0.1:{vps_port}", node_id=node_id)
        conn = get_db()
        cur = conn.cursor()
        cur.execute('INSERT INTO port_forwards (user_id, vps_container, vps_port, host_port, created_at) VALUES (?, ?, ?, ?, ?)',
                    (user_id, container, vps_port, host_port, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return host_port
    except Exception as e:
        logger.error(f"Failed to create port forward: {e}")
        return None

async def remove_port_forward(forward_id: int, is_admin: bool = False) -> tuple[bool, Optional[str]]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT user_id, vps_container, host_port FROM port_forwards WHERE id = ?', (forward_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, None
    user_id, container, host_port = row
    node_id = find_node_id_for_container(container)
    try:
        await execute_lxc(container, f"config device remove {container} tcp_proxy_{host_port}", node_id=node_id)
        await execute_lxc(container, f"config device remove {container} udp_proxy_{host_port}", node_id=node_id)
        cur.execute('DELETE FROM port_forwards WHERE id = ?', (forward_id,))
        conn.commit()
        conn.close()
        return True, user_id
    except Exception as e:
        logger.error(f"Failed to remove port forward {forward_id}: {e}")
        conn.close()
        return False, None

def get_user_forwards(user_id: str) -> List[Dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM port_forwards WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]

async def recreate_port_forwards(container_name: str) -> int:
    node_id = find_node_id_for_container(container_name)
    readded_count = 0
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT vps_port, host_port FROM port_forwards WHERE vps_container = ?', (container_name,))
    rows = cur.fetchall()
    for row in rows:
        vps_port = row['vps_port']
        host_port = row['host_port']
        try:
            await execute_lxc(container_name, f"config device add {container_name} tcp_proxy_{host_port} proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:{vps_port}", node_id=node_id)
            await execute_lxc(container_name, f"config device add {container_name} udp_proxy_{host_port} proxy listen=udp:0.0.0.0:{host_port} connect=udp:127.0.0.1:{vps_port}", node_id=node_id)
            logger.info(f"Re-added port forward {host_port}->{vps_port} for {container_name}")
            readded_count += 1
        except Exception as e:
            logger.error(f"Failed to re-add port forward {host_port}->{vps_port} for {container_name}: {e}")
    conn.close()
    return readded_count

def find_node_id_for_container(container_name: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT node_id FROM vps WHERE container_name = ?', (container_name,))
    row = cur.fetchone()
    conn.close()
    if row and row[0] is not None:
        return int(row[0])
    # Never fall back to hard-coded node 1. Respect the persisted deployment default.
    try:
        return _preferred_deployment_node_id()
    except Exception:
        return 1

# Initialize database
init_db()

# Load data at startup
vps_data = get_vps_data()
admin_data = {'admins': get_admins()}
_vps_data_loaded_once = True

# Auto-save flag to prevent constant file writes
_auto_save_pending = False

def mark_for_save():
    """Mark data for auto-save"""
    global _auto_save_pending
    _auto_save_pending = True

async def auto_save_task():
    """Background task to auto-save VPS data periodically"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            global _auto_save_pending
            if _auto_save_pending:
                save_vps_data()
                _auto_save_pending = False
                logger.debug("Auto-saved VPS data")
        except Exception as e:
            logger.error(f"Error in auto-save task: {e}")
        await asyncio.sleep(2)  # Check every 2 seconds

async def invite_startup_sync_task():
    await bot.wait_until_ready()
    for guild in list(bot.guilds):
        try:
            await sync_guild_invites(guild)
        except Exception as exc:
            logger.warning("Invite startup sync failed for guild %s: %s", guild.id, exc)
        await asyncio.sleep(0.25)

async def rotating_presence_task():
    """Background task to update bot watching status with VPS stats"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            now = datetime.now()
            total = running = expired = 0
            for user_vps_list in vps_data.values():
                for vps in user_vps_list:
                    total += 1
                    if vps.get('status') == 'running' and not vps.get('suspended'):
                        running += 1
                    exp = vps.get('expiration_date')
                    if exp and datetime.fromisoformat(exp) < now:
                        expired += 1
            slot_cap = DEPLOY_SLOT if DEPLOY_SLOT > 0 else 100
            status_name = f"🖥️ {total}/{slot_cap} VPS | 🟢 {running} Running | 🔴 {expired} Expired"
            await bot.change_presence(
                activity=discord.Activity(type=discord.ActivityType.watching, name=status_name)
            )
        except Exception as e:
            logger.error(f"Error in presence task: {e}")
        await asyncio.sleep(30)

def save_vps_data_immediate():
    """Immediate save - call this for critical operations"""
    save_vps_data()
    mark_for_save()  # Ensure it's saved

def verify_vps_persisted(vps: Dict[str, Any]) -> bool:
    """Verify a critical VPS record exists in SQLite after creation/update."""
    container_name = str(vps.get('container_name') or '').strip()
    if not container_name:
        return False
    conn = get_db()
    try:
        row = conn.execute('SELECT id FROM vps WHERE container_name = ?', (container_name,)).fetchone()
        if not row:
            return False
        vps['id'] = int(row['id'])
        return True
    finally:
        conn.close()

# Global settings from DB
CPU_THRESHOLD = int(get_setting('cpu_threshold', 90))
RAM_THRESHOLD = int(get_setting('ram_threshold', 90))
try:
    _persisted_ai_agent = get_setting('ai_agent_enabled', None)
    if _persisted_ai_agent is not None:
        _ai_agent_state['enabled'] = str(_persisted_ai_agent).strip().lower() in ('1', 'true', 'yes', 'on')
except Exception:
    logger.exception('Could not load persisted AI agent state; keeping environment default')

# Prefix is persisted in SQLite so it can be changed from Discord without
# editing/redeploying the bot. Environment remains the first-install fallback.
try:
    PREFIX = _normalize_prefix(get_setting('bot_prefix', PREFIX))
except (TypeError, ValueError):
    PREFIX = '1'
    set_setting('bot_prefix', PREFIX)

def _runtime_command_prefix(bot_instance, message):
    """Return the current prefix for every message. discord.py passes bot + message."""
    return PREFIX

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=_runtime_command_prefix, intents=intents, help_command=None)

# Resource monitoring settings (logging only)
resource_monitor_active = True

# ═══════════════════════════════════════════════════════════════════════════
# MODERN UI/UX SYSTEM - Beautiful Discord Embeds
# ═══════════════════════════════════════════════════════════════════════════

# Professional Color Palette
COLOR_PRIMARY = 0x2c3e50      # Dark slate blue
COLOR_SUCCESS = 0x27ae60      # Modern green  
COLOR_ERROR = 0xe74c3c        # Bright red
COLOR_WARNING = 0xf39c12      # Amber
COLOR_INFO = 0x3498db         # Ocean blue
COLOR_NETWORK = 0x16a085      # Teal
COLOR_EXPIRED = 0xc0392b      # Dark red
COLOR_ACTIVE = 0x16a085       # Teal green
COLOR_SUSPENDED = 0x95a5a6    # Gray
COLOR_NODE = 0x8e44ad         # Purple

# Helper function to truncate text
# Password generation and management functions
def generate_strong_password(length=16):
    """Generate a cryptographically strong password"""
    # Use mix of uppercase, lowercase, digits, and special characters
    charset = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(charset) for _ in range(length))
    return password

def sanitize_username_for_container(username: str) -> str:
    """
    Sanitize username for LXC container naming.
    LXC only allows alphanumeric and hyphen characters.
    Replace underscores, spaces, and other invalid chars with hyphens.
    """
    # Replace underscores and spaces with hyphens
    sanitized = username.replace('_', '-').replace(' ', '-')
    # Remove any character that's not alphanumeric or hyphen
    sanitized = ''.join(c for c in sanitized if c.isalnum() or c == '-')
    # Ensure it doesn't start or end with hyphen (LXC requirement)
    sanitized = sanitized.strip('-').lower()
    # Limit length to avoid issues (LXC container names have limits)
    sanitized = sanitized[:30]
    if not sanitized:
        sanitized = 'user'
    return sanitized

def get_vps_password(container_name):
    """Get password from VPS data"""
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps['container_name'] == container_name:
                return vps.get('root_password', None)
    return None

def set_vps_password(container_name, password):
    """Set password for VPS"""
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps['container_name'] == container_name:
                vps['root_password'] = password
                save_vps_data_immediate()
                return True
    return False

async def configure_ssh(container_name, node_id, password):
    """Install, repair and verify OpenSSH for password-based root access."""
    try:
        # Fail fast for stopped/missing instances instead of running repeated apt jobs.
        # Install only when sshd is absent; package manager output is preserved for diagnostics.
        install_cmd = r"""set -eu
export DEBIAN_FRONTEND=noninteractive
mkdir -p /var/run/sshd /run/sshd /etc/ssh/sshd_config.d
if command -v sshd >/dev/null 2>&1; then
  echo SSHD_ALREADY_INSTALLED
elif command -v apt-get >/dev/null 2>&1; then
  if ! dpkg-query -W -f='${Status}' openssh-server 2>/dev/null | grep -q 'install ok installed'; then
    timeout 75 apt-get update -o Acquire::Retries=1 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15
    timeout 90 apt-get install -y --no-install-recommends openssh-server openssh-client
  fi
elif command -v apk >/dev/null 2>&1; then
  timeout 90 apk add --no-cache openssh
elif command -v dnf >/dev/null 2>&1; then
  timeout 90 dnf install -y openssh-server openssh-clients
elif command -v yum >/dev/null 2>&1; then
  timeout 90 yum install -y openssh-server openssh-clients
elif command -v zypper >/dev/null 2>&1; then
  timeout 90 zypper --non-interactive install openssh-server openssh-clients
else
  echo 'Unsupported package manager' >&2; exit 20
fi
command -v sshd >/dev/null 2>&1 || { echo 'SSHD_INSTALL_MISSING' >&2; exit 21; }
"""
        await execute_lxc(container_name, f"exec {container_name} -- sh -c {shlex.quote(install_cmd)}",
                          node_id=node_id, timeout=190)

        max_auth = 4 if VPS_HARDEN_SSH else 6
        max_sessions = 6 if VPS_HARDEN_SSH else 10
        config_script = r"""set -eu
mkdir -p /etc/ssh/sshd_config.d /var/run/sshd /run/sshd
if [ -f /etc/ssh/sshd_config ]; then
  cp -n /etc/ssh/sshd_config /etc/ssh/sshd_config.voxelcloud-backup 2>/dev/null || true
  sed -i -E \
    -e 's/^[[:space:]]*#?[[:space:]]*PasswordAuthentication[[:space:]].*$/PasswordAuthentication yes/' \
    -e 's/^[[:space:]]*#?[[:space:]]*KbdInteractiveAuthentication[[:space:]].*$/KbdInteractiveAuthentication no/' \
    -e 's/^[[:space:]]*#?[[:space:]]*PubkeyAuthentication[[:space:]].*$/PubkeyAuthentication yes/' \
    -e 's/^[[:space:]]*#?[[:space:]]*PermitRootLogin[[:space:]].*$/PermitRootLogin yes/' \
    -e 's/^[[:space:]]*#?[[:space:]]*UsePAM[[:space:]].*$/UsePAM yes/' \
    -e 's/^[[:space:]]*#?[[:space:]]*AuthenticationMethods[[:space:]].*$/# AuthenticationMethods disabled by AxionHost/' \
    /etc/ssh/sshd_config
fi
cat > /etc/ssh/sshd_config.d/00-voxelcloud-access.conf <<'SSHEOF'
# AxionHost SSH access baseline
Port 22
AddressFamily any
ListenAddress 0.0.0.0
ListenAddress ::
PasswordAuthentication yes
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin yes
PermitEmptyPasswords no
UsePAM yes
MaxAuthTries __MAX_AUTH__
MaxSessions __MAX_SESSIONS__
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
TCPKeepAlive yes
PrintMotd no
PrintLastLog yes
SSHEOF
sed -i 's/__MAX_AUTH__/__AUTH__/; s/__MAX_SESSIONS__/__SESS__/' /etc/ssh/sshd_config.d/00-voxelcloud-access.conf
if ! grep -Eq '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\\\.d/\\*\\\.conf' /etc/ssh/sshd_config 2>/dev/null; then
  printf '\nInclude /etc/ssh/sshd_config.d/*.conf\n' >> /etc/ssh/sshd_config
fi
if ! grep -RiqE '^[[:space:]]*Subsystem[[:space:]]+sftp[[:space:]]+' /etc/ssh/sshd_config /etc/ssh/sshd_config.d 2>/dev/null; then
  printf '\nSubsystem sftp internal-sftp\n' >> /etc/ssh/sshd_config.d/00-voxelcloud-access.conf
fi
mkdir -p /etc/profile.d
cat > /etc/profile.d/voxelcloud-env.sh <<'ENVEOF'
export HOME="${HOME:-/root}"
export USER="${USER:-root}"
export LOGNAME="${LOGNAME:-root}"
export SHELL="${SHELL:-/bin/bash}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"
ENVEOF
chmod 0644 /etc/profile.d/voxelcloud-env.sh
""".replace("__AUTH__", str(max_auth)).replace("__SESS__", str(max_sessions))
        await execute_lxc(container_name, f"exec {container_name} -- sh -c {shlex.quote(config_script)}",
                          node_id=node_id, timeout=60)

        password_cmd = f"printf '%s\\n' {shlex.quote('root:' + password)} | chpasswd"
        await execute_lxc(container_name, f"exec {container_name} -- sh -c {shlex.quote(password_cmd)}",
                          node_id=node_id, timeout=30)

        verify_cmd = r"""set -eu
mkdir -p /run/sshd /var/run/sshd
sshd -t
EFFECTIVE="$(sshd -T 2>/dev/null || true)"
printf '%s\n' "$EFFECTIVE" | grep -E '^(passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|permitrootlogin|usepam|authenticationmethods) ' || true
printf '%s\n' "$EFFECTIVE" | grep -Eq '^passwordauthentication yes$' || { echo 'SSH_EFFECTIVE_PASSWORD_AUTH=NO'; exit 30; }
printf '%s\n' "$EFFECTIVE" | grep -Eq '^permitrootlogin yes$' || { echo 'SSH_EFFECTIVE_ROOT_LOGIN=NO'; exit 31; }
if printf '%s\n' "$EFFECTIVE" | grep -Eq '^authenticationmethods ' && ! printf '%s\n' "$EFFECTIVE" | grep -Eq '^authenticationmethods any$'; then
  echo 'SSH_EFFECTIVE_AUTH_METHODS_RESTRICTED'; exit 32
fi
(systemctl enable --now ssh 2>/dev/null || systemctl enable --now sshd 2>/dev/null ||  rc-update add sshd default 2>/dev/null || rc-service sshd restart 2>/dev/null ||  service ssh restart 2>/dev/null || /etc/init.d/ssh restart 2>/dev/null || true)
pgrep -x sshd >/dev/null 2>&1 || { echo 'SSHD_NOT_RUNNING'; exit 33; }
if command -v ss >/dev/null 2>&1; then
  ss -lnt 2>/dev/null | grep -Eq '(^|[[:space:]])[^ ]*:22[[:space:]]' || { echo 'SSHD_PORT_22_NOT_LISTENING'; exit 34; }
fi
echo 'SSH_EFFECTIVE_PASSWORD_AUTH=YES'
echo 'SSH_EFFECTIVE_ROOT_LOGIN=YES'
echo 'SSH_PORT_22=LISTENING'
"""
        out = await execute_lxc(container_name, f"exec {container_name} -- sh -c {shlex.quote(verify_cmd)}",
                                node_id=node_id, timeout=60)
        set_vps_password(container_name, password)
        logger.info("[SSH] %s verified: %s", container_name, str(out)[-800:])
        return True, password
    except Exception as e:
        logger.error(f"Failed to configure SSH for {container_name}: {e}")
        return False, str(e)

def truncate_text(text, max_length=1024):
    if not text:
        return text
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

# Create professional embeds with modern styling
def create_embed(title, description="", color=COLOR_PRIMARY):
    """Create a beautiful, modern embed"""
    embed = discord.Embed(
        title=f"🌟 {title}",
        description=truncate_text(description, 4096),
        color=color
    )
    embed.set_thumbnail(url=BOT_THUMBNAIL_URL)
    embed.set_footer(
        text="✨ EVM-V3",
        icon_url=BOT_ICON_URL
    )
    embed.timestamp = datetime.now()
    return embed

def add_field(embed, name, value, inline=False):
    """Add a field with professional formatting"""
    embed.add_field(
        name=f"➤ {name}",
        value=truncate_text(value, 1024),
        inline=inline
    )
    return embed

def create_success_embed(title, description=""):
    """Create a success embed (green)"""
    return create_embed(title, description, COLOR_SUCCESS)

def create_error_embed(title, description=""):
    """Create an error embed (red)"""
    return create_embed(title, description, COLOR_ERROR)

def create_info_embed(title, description=""):
    """Create an info embed (blue)"""
    return create_embed(title, description, COLOR_INFO)

def create_warning_embed(title, description=""):
    """Create a warning embed (orange)"""
    return create_embed(title, description, COLOR_WARNING)

# Visual helper functions
def create_progress_bar(value, max_value=100, length=15):
    """Create a visual progress bar with emoji blocks"""
    if max_value == 0:
        percentage = 0
    else:
        percentage = int((value / max_value) * 100)
    filled = int((percentage / 100) * length)
    bar = "🟩" * filled + "⬜" * (length - filled)
    return f"{bar} `{percentage}%`"

def format_expiration(vps):
    """Format expiration date with visual badge"""
    if not vps.get('expiration_date'):
        return "🔵 No expiration"
    
    exp_dt = datetime.fromisoformat(vps['expiration_date'])
    days = (exp_dt - datetime.now()).days
    
    if days < 0:
        return f"🔴 **EXPIRED** (`{abs(days)}d ago`)"
    elif days <= EXPIRATION_WARNING_DAYS:
        return f"🟡 **EXPIRING** (`{days}d left`)"
    else:
        return f"🟢 **ACTIVE** (`{days}d left`)"

def create_vps_card(vps, index):
    """Create a formatted VPS information card"""
    node = get_node(vps.get('node_id', 1))
    status_emoji = "🟢" if (vps.get('status') == 'running' and not vps.get('suspended')) else "🟡" if vps.get('suspended') else "🔴"
    node_emoji = "📍" if (node and node.get('is_local')) else "🌐"
    
    card = (
        f"**#{index}** `{vps['container_name']}`\n"
        f"{status_emoji} {vps.get('status', 'unknown').upper()}"
    )
    if vps.get('suspended'):
        card += " (SUSPENDED)"
    
    card += (
        f"\n⚙️ **Config:** {vps.get('config', 'Custom')}\n"
        f"💾 **RAM:** {vps['ram']} | **CPU:** {vps['cpu']} | **Disk:** {vps['storage']}\n"
        f"{node_emoji} **Node:** {node['name'] if node else 'Unknown'}\n"
        f"🧩 **Backend:** {vps.get('backend', 'lxc').upper()}\n"
        f"⏰ **Expiration:** {format_expiration(vps)}"
    )
    return card

# Admin checks
def is_admin():
    async def predicate(ctx):
        user_id = str(ctx.author.id)
        if user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", []):
            return True
        raise commands.CheckFailure("You need admin permissions to use this command. Contact support.")
    return commands.check(predicate)

def is_main_admin():
    async def predicate(ctx):
        if str(ctx.author.id) == str(MAIN_ADMIN_ID):
            return True
        raise commands.CheckFailure("Only the main admin can use this command.")
    return commands.check(predicate)


# ─────────────────────────────────────────────────────────────────────────────
# -----------------------------------------------------------------------------
# Cloudflare + Pterodactyl integrations
# -----------------------------------------------------------------------------
async def _guest_exec_lxc(container_name: str, node_id: int, command: str, timeout: int = 120) -> str:
    return await execute_lxc(container_name, f"exec {container_name} -- bash -lc {shlex.quote(command)}", node_id=node_id, timeout=timeout)

async def _guest_is_running(container_name: str, node_id: int) -> bool:
    """Return True only when the target LXC is actually running."""
    try:
        stats = await asyncio.wait_for(get_container_stats(container_name, node_id), timeout=15)
        return str(stats.get('status', '')).strip().lower() == 'running'
    except Exception as exc:
        logger.debug('Guest running-state check failed for %s: %s', container_name, exc)
        return False


async def _safe_cloudflare_install(container_name: str, node_id: int) -> Optional[str]:
    """Install Cloudflare only when the guest is running; otherwise defer safely."""
    if not await _guest_is_running(container_name, node_id):
        logger.info('Skipping Cloudflare setup for stopped/unavailable VPS %s; it will be retried when the VPS is running.', container_name)
        return None
    return await cloudflare_guest_install(container_name, node_id)


async def cloudflare_guest_install(container_name: str, node_id: int) -> str:
    """Install/repair a remotely-managed Cloudflare Tunnel safely and quickly."""
    if not CLOUDFLARE_INSTALL_ENABLED:
        raise RuntimeError('Cloudflare installation is disabled by CLOUDFLARE_INSTALL_ENABLED=false.')
    if not await _guest_is_running(container_name, node_id):
        raise RuntimeError(f'VPS `{container_name}` is not running; start the VPS before Cloudflare setup.')
    token_b64 = base64.b64encode(CLOUDFLARE_TUNNEL_TOKEN.encode('utf-8')).decode('ascii') if CLOUDFLARE_TUNNEL_TOKEN else ''
    script = r'''set -u
export DEBIAN_FRONTEND=noninteractive
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ARCH="$(uname -m 2>/dev/null || true)"
case "$ARCH" in
  x86_64|amd64) CFARCH=amd64 ;;
  aarch64|arm64) CFARCH=arm64 ;;
  armv7l|armv6l) CFARCH=arm ;;
  *) echo "CLOUDFLARED_ERROR=unsupported_arch:$ARCH"; exit 2 ;;
esac
install_pkgs() {
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y >/dev/null 2>&1 || true
    apt-get install -y curl ca-certificates coreutils procps iproute2 dnsutils netcat-openbsd >/dev/null 2>&1 || true
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache curl ca-certificates coreutils procps iproute2 bind-tools netcat-openbsd >/dev/null 2>&1 || true
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y curl ca-certificates coreutils procps iproute bind-utils nmap-ncat >/dev/null 2>&1 || true
  elif command -v yum >/dev/null 2>&1; then
    yum install -y curl ca-certificates coreutils procps iproute bind-utils >/dev/null 2>&1 || true
  elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive install curl ca-certificates coreutils procps iproute2 bind-utils netcat-openbsd >/dev/null 2>&1 || true
  fi
}
command -v curl >/dev/null 2>&1 || install_pkgs
command -v curl >/dev/null 2>&1 || { echo "CLOUDFLARED_ERROR=curl_not_available"; exit 20; }
mkdir -p /etc/cloudflared /var/log/cloudflared /etc/systemd/system
NEED_DOWNLOAD=0
if [ ! -x /usr/local/bin/cloudflared ]; then
  NEED_DOWNLOAD=1
elif ! /usr/local/bin/cloudflared --version >/tmp/cloudflared-version.out 2>&1; then
  NEED_DOWNLOAD=1
elif ! /usr/local/bin/cloudflared tunnel run --help 2>&1 | grep -q -- '--token-file'; then
  NEED_DOWNLOAD=1
fi
if [ "$NEED_DOWNLOAD" = "1" ]; then
  TMP_CF=/usr/local/bin/cloudflared.part
  rm -f "$TMP_CF"
  if ! curl -fL --retry 5 --retry-all-errors --retry-delay 2 --connect-timeout 15 --max-time 180 \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CFARCH}" -o "$TMP_CF"; then
    echo "CLOUDFLARED_ERROR=download_failed"; rm -f "$TMP_CF"; exit 21
  fi
  test -s "$TMP_CF" || { echo "CLOUDFLARED_ERROR=download_empty"; rm -f "$TMP_CF"; exit 22; }
  chmod 0755 "$TMP_CF"
  if ! "$TMP_CF" --version >/tmp/cloudflared-version.out 2>&1; then
    echo "CLOUDFLARED_ERROR=invalid_binary"; cat /tmp/cloudflared-version.out 2>/dev/null || true; rm -f "$TMP_CF"; exit 23
  fi
  mv -f "$TMP_CF" /usr/local/bin/cloudflared
fi
/usr/local/bin/cloudflared --version 2>&1 | head -n1
systemctl stop cloudflared.service >/dev/null 2>&1 || true
systemctl disable cloudflared.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/cloudflared.service /etc/systemd/system/multi-user.target.wants/cloudflared.service
systemctl daemon-reload >/dev/null 2>&1 || true
if [ -n "__CF_TOKEN_B64__" ]; then
  printf '%s' '__CF_TOKEN_B64__' | base64 -d > /etc/cloudflared/tunnel-token
  chmod 0600 /etc/cloudflared/tunnel-token
  test -s /etc/cloudflared/tunnel-token || { echo "CLOUDFLARED_ERROR=token_write_failed"; exit 24; }
  cat > /etc/systemd/system/cloudflared.service <<'UNITEOF'
[Unit]
Description=AxionHost Cloudflare Tunnel
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=20

[Service]
Type=simple
User=root
Environment=TUNNEL_DNS_RESOLVER_ADDRS=1.1.1.1:53
Environment=TUNNEL_TOKEN_FILE=/etc/cloudflared/tunnel-token
# Use the documented TUNNEL_TOKEN_FILE environment variable as the primary
# authentication path. This avoids CLI parser/version quirks around --token-file.
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate --protocol auto --edge-ip-version 4 --retries 5 --loglevel info --log-directory /var/log/cloudflared run
Restart=always
RestartSec=5
TimeoutStartSec=0
TimeoutStopSec=20
KillMode=mixed
NoNewPrivileges=true
PrivateTmp=true
LimitNOFILE=1048576
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNITEOF
  chmod 0644 /etc/systemd/system/cloudflared.service
  systemctl daemon-reload
  systemctl enable cloudflared.service >/dev/null 2>&1 || true
  systemctl reset-failed cloudflared.service >/dev/null 2>&1 || true
  systemctl start --no-block cloudflared.service >/dev/null 2>&1 || true
  for i in 1 2 3 4 5 6 7 8; do
    if systemctl is-active --quiet cloudflared.service; then echo "CLOUDFLARED_SERVICE=ACTIVE"; break; fi
    if systemctl is-failed --quiet cloudflared.service; then
      echo "CLOUDFLARED_SERVICE=FAILED"
      journalctl -u cloudflared.service -n 20 --no-pager 2>&1 | sed -E 's/eyJ[A-Za-z0-9._-]+/<TOKEN_REDACTED>/g' || true
      break
    fi
    [ "$i" -lt 8 ] && sleep 1
  done
  if ! systemctl is-active --quiet cloudflared.service && ! systemctl is-failed --quiet cloudflared.service; then echo "CLOUDFLARED_SERVICE=STARTING"; fi
else
  rm -f /etc/systemd/system/cloudflared.service /etc/systemd/system/multi-user.target.wants/cloudflared.service
  systemctl daemon-reload >/dev/null 2>&1 || true
  echo "CLOUDFLARED_INSTALLED=YES"
  echo "TUNNEL_SERVICE=NOT_CONFIGURED"
  echo "TUNNEL_TOKEN=NOT_SET"
fi
'''.replace('__CF_TOKEN_B64__', token_b64)
    async with _get_tunnel_lock(f"cloudflare:{node_id}:{container_name}"):
        return await _guest_exec_lxc(container_name, node_id, script, timeout=240)


async def cloudflare_guest_status(container_name: str, node_id: int) -> str:
    """Actionable Cloudflare diagnostics; never print the tunnel token."""
    command = r'''set +e
printf '=== cloudflared version ===\n'; cloudflared --version 2>&1 || true
printf '=== service ===\n'; systemctl is-active cloudflared.service 2>&1 || true; systemctl is-enabled cloudflared.service 2>&1 || true
printf '=== service status ===\n'; systemctl --no-pager --full status cloudflared.service 2>&1 | sed -n '1,28p' || true
printf '=== recent logs ===\n'; journalctl -u cloudflared.service -n 35 --no-pager 2>&1 | sed -E 's/eyJ[A-Za-z0-9._-]+/<TOKEN_REDACTED>/g' || true
printf '=== tunnel preflight ===\n'; timeout 18 cloudflared tunnel diag 2>&1 || true
printf '=== DNS ===\n'; getent hosts region1.v2.argotunnel.com 2>&1 || true
printf '=== HTTPS ===\n'; curl -4 -fsS --max-time 8 https://www.cloudflare.com/cdn-cgi/trace >/dev/null && echo INTERNET_OK || echo INTERNET_FAIL
'''
    return await _guest_exec_lxc(container_name, node_id, command, timeout=60)


def _ptero_headers() -> Dict[str, str]:
    if not PTERO_API_KEY:
        raise RuntimeError('PTERO_API_KEY is not configured.')
    return {'Authorization': f'Bearer {PTERO_API_KEY}', 'Accept': 'Application/vnd.pterodactyl.v1+json', 'Content-Type': 'application/json'}

async def ptero_request(method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    if not PTERO_PANEL_URL:
        raise RuntimeError('PTERO_PANEL_URL is not configured.')
    url = PTERO_PANEL_URL + path
    headers = _ptero_headers()
    def do_request():
        r = requests.request(method.upper(), url, headers=headers, json=payload, timeout=25)
        if r.status_code >= 400:
            try: detail = r.json()
            except Exception: detail = r.text[:1000]
            raise RuntimeError(f'Pterodactyl API HTTP {r.status_code}: {detail}')
        if not r.content: return {}
        return r.json()
    return await asyncio.to_thread(do_request)

# KVM/libvirt backend helpers
# ─────────────────────────────────────────────────────────────────────────────
def get_vps_backend(container_name: str) -> str:
    conn = get_db()
    try:
        row = conn.execute('SELECT backend FROM vps WHERE container_name = ?', (container_name,)).fetchone()
        return (row[0] if row and row[0] else 'lxc').lower()
    finally:
        conn.close()


def _kvm_local_capabilities() -> Dict[str, Any]:
    return {
        'enabled': KVM_ENABLED,
        'virsh': shutil.which('virsh'),
        'virt_install': shutil.which('virt-install'),
        'qemu_img': shutil.which('qemu-img'),
        'kvm_device': os.path.exists('/dev/kvm'),
        'ready': bool(KVM_ENABLED and shutil.which('virsh') and shutil.which('virt-install') and shutil.which('qemu-img') and os.path.exists('/dev/kvm')),
    }



def _kvm_host_missing(caps: Optional[Dict[str, Any]] = None) -> List[str]:
    caps = caps or _kvm_local_capabilities()
    missing = []
    if not caps.get('virsh'): missing.append('virsh')
    if not caps.get('virt_install'): missing.append('virt-install')
    if not caps.get('qemu_img'): missing.append('qemu-img')
    if not caps.get('kvm_device'): missing.append('/dev/kvm')
    return missing


async def _ensure_kvm_host_ready(auto_install: bool = True) -> Dict[str, Any]:
    """Repair local KVM/libvirt packages and services where possible.

    /dev/kvm cannot be created by installing a Python package. If this bot is
    itself inside a VM/LXC without nested KVM passthrough, the result explains
    that the parent provider must expose KVM.
    """
    caps = _kvm_local_capabilities()
    if caps['ready']:
        return {'ready': True, 'caps': caps, 'actions': [], 'error': None}
    if not KVM_ENABLED:
        return {'ready': False, 'caps': caps, 'actions': [], 'error': 'KVM_ENABLED is disabled.'}
    actions, errors = [], []
    if auto_install and (not caps.get('virsh') or not caps.get('virt_install') or not caps.get('qemu_img')):
        try:
            if shutil.which('apt-get'):
                actions.append('Installing qemu-kvm, qemu-utils, libvirt and virtinst')
                await _run_local_process(['apt-get', 'update'], timeout=300, check=False)
                await _run_local_process(['env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'install', '-y', 'qemu-kvm', 'qemu-utils', 'libvirt-daemon-system', 'libvirt-clients', 'virtinst'], timeout=600)
            elif shutil.which('dnf'):
                actions.append('Installing QEMU/libvirt/virt-install')
                await _run_local_process(['dnf', '-y', 'install', 'qemu-kvm', 'qemu-img', 'libvirt', 'libvirt-client', 'virt-install'], timeout=600)
            elif shutil.which('zypper'):
                actions.append('Installing QEMU/libvirt/virt-install')
                await _run_local_process(['zypper', '--non-interactive', 'install', 'qemu-x86', 'qemu-tools', 'libvirt', 'libvirt-client', 'virt-install'], timeout=600)
            elif shutil.which('apk'):
                actions.append('Installing QEMU/libvirt/virt-install')
                await _run_local_process(['apk', 'add', '--no-cache', 'qemu-system-x86_64', 'qemu-img', 'libvirt', 'libvirt-client', 'virt-install'], timeout=600)
            else:
                errors.append('No supported package manager found.')
        except Exception as exc:
            errors.append(f'Package installation failed: {exc}')

    if shutil.which('modprobe'):
        for module in ('kvm', 'kvm_intel', 'kvm_amd'):
            try:
                await _run_local_process(['modprobe', module], timeout=20, check=False)
            except Exception:
                pass

    if shutil.which('systemctl'):
        for unit in ('virtqemud.socket', 'virtlogd.socket', 'libvirtd.socket', 'libvirtd.service'):
            try:
                await _run_local_process(['systemctl', 'enable', '--now', unit], timeout=45, check=False)
            except Exception:
                pass

    caps = _kvm_local_capabilities()
    if caps['ready']:
        try:
            await _run_local_process(['virsh', '-c', 'qemu:///system', 'list', '--all'], timeout=30)
        except Exception as exc:
            caps['ready'] = False
            errors.append(f'libvirt qemu:///system failed: {exc}')

    if not caps.get('kvm_device'):
        flags = ''
        try:
            flags = await _run_local_process(['sh', '-lc', "grep -m1 -oE 'vmx|svm' /proc/cpuinfo 2>/dev/null || true"], timeout=10, check=False)
        except Exception:
            pass
        nested = []
        for path in ('/sys/module/kvm_intel/parameters/nested', '/sys/module/kvm_amd/parameters/nested'):
            if os.path.exists(path):
                try: nested.append(f'{path}={Path(path).read_text().strip()}')
                except Exception: pass
        if flags:
            errors.append('CPU virtualization flag is visible, but /dev/kvm is unavailable. ' + ('; '.join(nested) + '. ' if nested else '') + 'Enable nested KVM in the parent hypervisor/provider and expose /dev/kvm.')
        else:
            errors.append('Hardware virtualization is not exposed to this host. Enable VT-x/AMD-V and nested KVM in the parent hypervisor/provider, then expose /dev/kvm.')
    return {'ready': bool(caps.get('ready')), 'caps': caps, 'actions': actions, 'error': '; '.join(errors) if errors else None}

async def get_virtualization_capabilities(node_id: int = 1) -> Dict[str, Any]:
    node = get_node(node_id)
    if not node:
        return {'lxc': False, 'kvm': False, 'reason': 'Node not found'}
    if not node.get('is_local'):
        return {'lxc': True, 'kvm': False, 'reason': 'KVM requires a local libvirt host'}
    caps = _kvm_local_capabilities()
    return {'lxc': bool(shutil.which(LXC_CMD)), 'kvm': caps['ready'], 'kvm_details': caps}


async def _run_local_process(args: List[str], timeout: int = 120, check: bool = True) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=max(5, int(timeout)))
    except asyncio.TimeoutError:
        if proc.returncode is None:
            try: os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try: proc.kill()
                except ProcessLookupError: pass
            try: await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                try: os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    try: proc.kill()
                    except ProcessLookupError: pass
                try: await asyncio.wait_for(proc.wait(), timeout=2)
                except asyncio.TimeoutError: pass
        raise TimeoutError(f"Command timed out after {timeout}s")
    except asyncio.CancelledError:
        if proc.returncode is None:
            try: os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try: proc.kill()
                except ProcessLookupError: pass
            try: await asyncio.wait_for(proc.wait(), timeout=3)
            except Exception:
                try: os.killpg(proc.pid, signal.SIGKILL)
                except Exception: pass
        raise
    out = stdout.decode(errors='replace').strip()
    err = stderr.decode(errors='replace').strip()
    if check and proc.returncode != 0:
        raise RuntimeError(err or out or f"Command failed: {' '.join(args)}")
    return out


async def execute_kvm(vm_name: str, command: str, node_id: int = 1):
    node = get_node(node_id)
    if not node or not node.get('is_local'):
        raise RuntimeError('KVM management currently requires a local libvirt node.')
    caps = _kvm_local_capabilities()
    if not caps['ready']:
        raise RuntimeError('KVM is unavailable. Install/enable libvirt, virt-install, qemu-img and hardware virtualization (/dev/kvm).')
    parts = shlex.split(command)
    if not parts:
        return await _run_local_process(['virsh', 'dominfo', vm_name])
    op = parts[0].lower()
    if op == 'list':
        return await _run_local_process(['virsh', 'list', '--all'])
    if op == 'info':
        return await _run_local_process(['virsh', 'dominfo', vm_name])
    if op == 'start':
        return await _run_local_process(['virsh', 'start', vm_name])
    if op == 'stop':
        await _run_local_process(['virsh', 'shutdown', vm_name], check=False)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            state = (await _run_local_process(['virsh', 'domstate', vm_name], check=False)).strip().lower()
            if 'shut off' in state or 'shutoff' in state:
                return f'{vm_name} is shut off'
            await asyncio.sleep(2)
        raise TimeoutError(f'KVM `{vm_name}` did not shut down within 60 seconds; no resource changes were applied.')
    if op == 'restart':
        await _run_local_process(['virsh', 'reboot', vm_name], check=False)
        return f'Reboot requested for {vm_name}'
    if op == 'delete':
        await _run_local_process(['virsh', 'destroy', vm_name], check=False)
        return await _run_local_process(['virsh', 'undefine', vm_name, '--remove-all-storage'])
    if op == 'snapshot' and len(parts) >= 2:
        sub = parts[1]
        if sub == 'list':
            return await _run_local_process(['virsh', 'snapshot-list', vm_name])
        if sub == 'create':
            snap = parts[2] if len(parts) >= 3 else f'snap-{int(time.time())}'
            return await _run_local_process(['virsh', 'snapshot-create-as', vm_name, snap])
        if sub == 'delete' and len(parts) >= 3:
            snap = parts[2].split('/', 1)[-1]
            return await _run_local_process(['virsh', 'snapshot-delete', vm_name, snap])
        if sub == vm_name and len(parts) >= 3:
            return await _run_local_process(['virsh', 'snapshot-create-as', vm_name, parts[2]])
    if op == 'config' and len(parts) >= 5 and parts[1] == 'set':
        key, value = parts[3], parts[4]
        if key == 'limits.memory':
            mem_mb = int(re.sub(r'[^0-9]', '', value) or '0')
            await _run_local_process(['virsh', 'setmaxmem', vm_name, f'{mem_mb}M', '--config'])
            return await _run_local_process(['virsh', 'setmem', vm_name, f'{mem_mb}M', '--config'])
        if key == 'limits.cpu':
            await _run_local_process(['virsh', 'setvcpus', vm_name, str(int(value)), '--maximum', '--config'])
            return await _run_local_process(['virsh', 'setvcpus', vm_name, str(int(value)), '--config'])
        if key.startswith('security.'):
            return f'{key} is LXC-specific; KVM already provides a hardware VM boundary.'
    if op == 'config' and len(parts) >= 6 and parts[1:3] == ['device', 'set'] and parts[4] == 'root' and parts[5].startswith('size='):
        # Shared LXC/KVM resize command: resize a file-backed KVM disk while shut off.
        size = parts[5].split('=', 1)[1]
        if not re.fullmatch(r'[1-9][0-9]*(?:\.[0-9]+)?(?:G|GB|M|MB)', size, re.I):
            raise ValueError(f'Invalid KVM disk size: {size}')
        size_arg = size.upper().replace('GB', 'G').replace('MB', 'M')
        state = (await _run_local_process(['virsh', 'domstate', vm_name])).strip().lower()
        if 'shut off' not in state and 'shutoff' not in state:
            raise RuntimeError('KVM must be shut off before resizing its disk.')
        rows = await _run_local_process(['virsh', 'domblklist', vm_name, '--details'])
        disk_source = None
        for line in str(rows).splitlines():
            cols = line.split()
            if len(cols) >= 5 and cols[0].lower() == 'file' and cols[1].lower() == 'disk':
                disk_source = cols[4]
                break
        if not disk_source or not disk_source.startswith('/'):
            raise RuntimeError('Could not locate a file-backed KVM disk; disk resize was not applied.')
        if not shutil.which('qemu-img'):
            raise RuntimeError('qemu-img is required to resize KVM disks.')
        return await _run_local_process(['qemu-img', 'resize', disk_source, size_arg])
    if op == 'exec':
        raise RuntimeError('!exec is supported for LXC VPS only. Use SSH for KVM.')
    raise RuntimeError(f'KVM backend does not support LXC command `{command}`.')



async def get_kvm_cpu_capabilities() -> Dict[str, Any]:
    """Read libvirt's host-specific KVM CPU capabilities.

    `virsh cpu-models` lists models known to QEMU, but a known model is not
    necessarily runnable on this particular host. `domcapabilities` reports
    `usable=yes/no` and blockers for the actual hypervisor, which prevents
    incompatible AMD models being offered on Intel hosts (and vice versa).
    """
    result: Dict[str, Any] = {'models': {}, 'host_vendor': None, 'raw': ''}
    if not shutil.which('virsh'):
        return result
    try:
        raw = await _run_local_process(['virsh', 'domcapabilities', 'qemu:///system'], timeout=25, check=False)
        result['raw'] = raw
        if not raw or '<domainCapabilities' not in raw:
            return result
        root = ET.fromstring(raw)
        cpu = root.find('./cpu')
        if cpu is None:
            return result
        for mode in cpu.findall('./mode'):
            mode_name = mode.get('name', '')
            if mode_name in ('host-model', 'host-passthrough', 'maximum'):
                result[mode_name] = mode.get('supported', 'no') == 'yes'
            if mode_name != 'custom':
                continue
            for model in mode.findall('./model'):
                name = (model.text or '').strip()
                if not name:
                    continue
                result['models'][name] = {
                    'usable': model.get('usable', 'no') == 'yes',
                    'vendor': model.get('vendor') or '',
                    'deprecated': model.get('deprecated', 'no') == 'yes',
                    'canonical': model.get('canonical') or name,
                }
        # Host vendor is exposed by the host-model/custom CPU capabilities on
        # recent libvirt versions. Fall back to lscpu/proc when absent.
        vendors = [str(v.get('vendor', '')).lower() for v in result['models'].values() if v.get('vendor')]
        if vendors:
            amd_count = sum('amd' in v for v in vendors)
            intel_count = sum('intel' in v for v in vendors)
            if amd_count and not intel_count:
                result['host_vendor'] = 'AMD'
            elif intel_count and not amd_count:
                result['host_vendor'] = 'Intel'
    except Exception as exc:
        logger.debug('KVM CPU capability parse failed: %s', exc)
    if not result.get('host_vendor'):
        try:
            lscpu = await _run_local_process(['lscpu'], timeout=10, check=False)
            m = re.search(r'^Vendor ID:\s*(.+)$', lscpu, re.M | re.I)
            vendor = (m.group(1).strip() if m else '')
            if not vendor:
                m = re.search(r'^vendor_id\s*:\s*(.+)$', await _run_local_process(['bash','-lc','grep -m1 vendor_id /proc/cpuinfo 2>/dev/null || true'], timeout=10, check=False), re.M | re.I)
                vendor = (m.group(1).strip() if m else '')
            if 'amd' in vendor.lower():
                result['host_vendor'] = 'AMD'
            elif 'intel' in vendor.lower():
                result['host_vendor'] = 'Intel'
        except Exception:
            pass
    return result


async def get_kvm_cpu_models() -> List[str]:
    """Return CPU models actually usable by this KVM host, best effort."""
    caps = await get_kvm_cpu_capabilities()
    usable = [name for name, info in caps.get('models', {}).items() if info.get('usable')]
    if usable:
        return sorted(set(usable))
    if not shutil.which('virsh'):
        return []
    try:
        out = await _run_local_process(['virsh', 'cpu-models', 'x86_64'], timeout=20, check=False)
        return sorted({line.strip() for line in out.splitlines() if line.strip() and not line.startswith('CPU model')})
    except Exception:
        return []


async def check_kvm_cpu_model_compatibility(model: str) -> Dict[str, Any]:
    """Check whether a named CPU can actually run on this KVM host."""
    requested = (model or '').strip()
    low = requested.lower()
    if low in ('', 'auto', 'default', 'host-model', 'host-passthrough', 'maximum'):
        return {'compatible': True, 'model': requested, 'reason': 'dynamic libvirt CPU mode'}
    caps = await get_kvm_cpu_capabilities()
    info = caps.get('models', {}).get(requested)
    if info is None:
        # Case-insensitive lookup for model names.
        for name, item in caps.get('models', {}).items():
            if name.lower() == requested.lower():
                info = item
                requested = name
                break
    if info is not None:
        if info.get('usable'):
            return {'compatible': True, 'model': requested, 'vendor': info.get('vendor', ''), 'reason': 'libvirt reports usable=yes'}
        # Pull blockers from the exact model entry in domain capabilities.
        blockers = []
        raw = caps.get('raw', '')
        try:
            root = ET.fromstring(raw)
            for b in root.findall('.//blockers'):
                if b.get('model') == requested:
                    blockers = [((f.text or '').strip()) for f in b.findall('./feature') if (f.text or '').strip()]
                    break
        except Exception:
            pass
        return {'compatible': False, 'model': requested, 'vendor': info.get('vendor', ''), 'blockers': blockers, 'reason': 'libvirt reports usable=no'}
    # Older libvirt may not expose model usability. Use virsh cpu-compare.
    if shutil.which('virsh'):
        path = None
        try:
            with tempfile.NamedTemporaryFile('w', prefix='voxelcloud-cpu-', suffix='.xml', delete=False) as fh:
                path = fh.name
                fh.write(f'<cpu mode="custom"><model fallback="forbid">{requested}</model></cpu>')
            # Capture stderr too because virsh prints incompatibility diagnostics there.
            proc = await asyncio.create_subprocess_exec(
                'virsh', 'cpu-compare', path, '--error',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
            out = (stdout.decode(errors='replace') + '\n' + stderr.decode(errors='replace')).strip()
            bad = proc.returncode != 0 or 'incompatible with host CPU' in out.lower() or 'failed to compare' in out.lower()
            return {'compatible': not bad, 'model': requested, 'reason': out[-700:] or 'cpu-compare completed'}
        except Exception as exc:
            return {'compatible': True, 'model': requested, 'reason': f'compatibility could not be verified: {exc}'}
        finally:
            if path:
                try: os.remove(path)
                except OSError: pass
    return {'compatible': True, 'model': requested, 'reason': 'compatibility could not be verified'}


def classify_kvm_cpu_model(model: str) -> str:
    m = model.lower().replace('_', '-').replace(' ', '-')
    intel_tokens = ('intel', 'xeon', 'core-', 'core2', 'haswell', 'broadwell', 'skylake', 'cascadelake', 'cooperlake', 'icelake', 'sapphirerapids', 'emeraldrapids', 'westmere', 'nehalem', 'sandybridge', 'ivybridge', 'penryn', 'conroe', 'knl')
    amd_tokens = ('amd', 'epyc', 'opteron', 'athlon', 'phenom', 'zen', 'ryzen')
    if any(t in m for t in intel_tokens):
        return 'intel'
    if any(t in m for t in amd_tokens):
        return 'amd'
    return 'other'


def processor_display_name(model: Optional[str]) -> str:
    return {'host-model': 'Host Model', 'host-passthrough': 'Host Passthrough', 'maximum': 'Maximum'}.get(model or '', model or 'libvirt-default')


async def ensure_kvm_network() -> Dict[str, Any]:
    """Validate/repair the libvirt network used by KVM guests.

    The default NAT network is deliberately self-contained: libvirt provides
    DHCP/DNS and NAT.  We also verify that the bridge exists and that IPv4
    forwarding is enabled before a VM is started.
    """
    if not shutil.which('virsh'):
        raise RuntimeError('virsh is required for KVM networking.')
    conn = 'qemu:///system'
    try:
        await _run_local_process(['sysctl', '-w', 'net.ipv4.ip_forward=1'], timeout=10, check=False)
    except Exception:
        pass
    netinfo = await _run_local_process(['virsh', '-c', conn, 'net-info', KVM_NETWORK], timeout=20, check=False)
    if not netinfo:
        if KVM_NETWORK != 'default':
            raise RuntimeError(f'libvirt network `{KVM_NETWORK}` does not exist. Create it or set KVM_NETWORK in .env.')
        xml = """<network>
  <name>default</name>
  <forward mode='nat'/>
  <bridge name='virbr0' stp='on' delay='0'/>
  <ip address='192.168.122.1' netmask='255.255.255.0'>
    <dhcp><range start='192.168.122.2' end='192.168.122.254'/></dhcp>
  </ip>
</network>"""
        xml_path = '/tmp/voxelcloud-default-network.xml'
        Path(xml_path).write_text(xml, encoding='utf-8')
        try:
            await _run_local_process(['virsh', '-c', conn, 'net-define', xml_path], timeout=30)
        finally:
            try: os.remove(xml_path)
            except OSError: pass
        netinfo = await _run_local_process(['virsh', '-c', conn, 'net-info', KVM_NETWORK], timeout=20, check=False)
    active = re.search(r'\bActive:\s+(yes|no)', netinfo, re.I)
    if active and active.group(1).lower() != 'yes':
        start_out = await _run_local_process(['virsh', '-c', conn, 'net-start', KVM_NETWORK], timeout=45, check=False)
        netinfo = await _run_local_process(['virsh', '-c', conn, 'net-info', KVM_NETWORK], timeout=20, check=False)
        active = re.search(r'\bActive:\s+(yes|no)', netinfo, re.I)
        if active and active.group(1).lower() != 'yes':
            raise RuntimeError(f'Libvirt network `{KVM_NETWORK}` did not become active. {start_out[-500:]}')
    await _run_local_process(['virsh', '-c', conn, 'net-autostart', KVM_NETWORK], timeout=30, check=False)
    xml = await _run_local_process(['virsh', '-c', conn, 'net-dumpxml', KVM_NETWORK], timeout=20, check=False)
    if not xml:
        raise RuntimeError(f'Could not inspect libvirt network `{KVM_NETWORK}`.')
    forward = re.search(r'<forward\b[^>]*mode=["\'](nat|route|bridge|open|vepa|private|passthrough)["\']', xml, re.I)
    has_ipv4 = bool(re.search(r'<ip\b[^>]*address=["\'](?:[0-9]{1,3}\.){3}[0-9]{1,3}', xml, re.I))
    has_dhcp4 = bool(re.search(r'<dhcp>.*?<range\b', xml, re.I | re.S))
    if not has_ipv4 or not has_dhcp4:
        raise RuntimeError(f'KVM network `{KVM_NETWORK}` is active but has no IPv4 DHCP configuration. Use an IPv4 NAT/route network with DHCP.')
    bridge_m = re.search(r'<bridge\b[^>]*name=["\']([^"\']+)', xml, re.I)
    bridge = bridge_m.group(1) if bridge_m else ''
    if bridge and shutil.which('ip'):
        bridge_check = await _run_local_process(['ip','link','show','dev',bridge], timeout=10, check=False)
        if not bridge_check:
            await _run_local_process(['virsh','-c',conn,'net-destroy',KVM_NETWORK], timeout=30, check=False)
            await _run_local_process(['virsh','-c',conn,'net-start',KVM_NETWORK], timeout=45, check=False)
    return {'name': KVM_NETWORK, 'active': True, 'forward_mode': forward.group(1).lower() if forward else 'unknown', 'ipv4_dhcp': True, 'bridge': bridge or None, 'xml': xml}

async def create_kvm_instance(vm_name: str, image_ref: str, node_id: int, ram_gb: int, cpu: int, disk_gb: int, root_password: str, cpu_model: str = 'auto') -> Dict[str, Any]:
    raise RuntimeError('KVM VPS creation is disabled by the bot administrator. Please select LXC. Existing KVM VPS management is unchanged.')
    node = get_node(node_id)
    if not node or not node.get('is_local'):
        raise RuntimeError('KVM provisioning requires a local node.')
    caps = _kvm_local_capabilities()
    if not caps['ready']:
        repair = await _ensure_kvm_host_ready(auto_install=True)
        caps = repair['caps']
        if not caps['ready']:
            missing = _kvm_host_missing(caps)
            detail = repair.get('error') or 'KVM host prerequisites could not be repaired.'
            if missing: detail += ' Still missing: ' + ', '.join(missing) + '.'
            raise RuntimeError(detail)
    image = KVM_SUPPORTED_IMAGES.get(image_ref)
    if not image:
        raise RuntimeError(f'OS `{image_ref}` is not currently supported for KVM. Supported: {", ".join(KVM_SUPPORTED_IMAGES)}')
    os.makedirs(KVM_IMAGE_DIR, exist_ok=True)

    image_url = image['url']

    # Fail early with a useful message instead of letting QEMU fail after a
    # long boot attempt.  32GB+ guests are valid; they simply need enough
    # host RAM and disk capacity.
    # Capacity check: qcow2 is sparse, so the virtual disk size must NOT be
    # treated as immediately allocated host disk. The old check rejected valid
    # 32GB/80GB VPS requests on hosts that had enough real free space for the
    # image + metadata but not the full virtual disk size.
    try:
        meminfo = Path('/proc/meminfo').read_text(errors='ignore')
        avail_kib = int(re.search(r'^MemAvailable:\s+(\d+)', meminfo, re.M).group(1)) if re.search(r'^MemAvailable:\s+(\d+)', meminfo, re.M) else 0
        required_kib = int((ram_gb + KVM_MIN_FREE_MEMORY_GB) * 1024)
        if avail_kib and avail_kib < required_kib:
            raise RuntimeError(f'Not enough host memory for {ram_gb}GB KVM VPS. Available: {avail_kib/1024:.1f}GB; required including reserve: {ram_gb + KVM_MIN_FREE_MEMORY_GB:.1f}GB.')
    except RuntimeError:
        raise
    except Exception:
        pass
    try:
        st = shutil.disk_usage(KVM_IMAGE_DIR)
        # Estimate only image download + qcow metadata/headroom. qemu-img
        # resize creates a sparse virtual size and does not allocate disk_gb.
        image_estimate = 3 * 1024**3
        required_bytes = image_estimate + int(KVM_MIN_FREE_DISK_GB * 1024**3)
        if st.free < required_bytes:
            raise RuntimeError(f'Not enough host disk space for KVM provisioning. Free: {st.free/1024**3:.1f}GB; keep at least {KVM_MIN_FREE_DISK_GB:.1f}GB free plus image space.')
    except RuntimeError:
        raise
    except Exception:
        pass

    base_name = os.path.basename(image_url.split('?', 1)[0]) or f'{image_ref.replace(":", "-").replace("/", "-")}.qcow2'
    base = os.path.join(KVM_IMAGE_DIR, base_name)
    disk = os.path.join(KVM_IMAGE_DIR, f'{vm_name}.qcow2')
    user_data = os.path.join(KVM_IMAGE_DIR, f'{vm_name}-user-data.yaml')
    network_config = os.path.join(KVM_IMAGE_DIR, f'{vm_name}-network-config.yaml')
    mac_bytes = bytearray(uuid.uuid4().bytes[:6])
    mac_bytes[0] = (mac_bytes[0] & 0xFE) | 0x02
    vm_mac = ':'.join(f'{b:02x}' for b in mac_bytes)

    # A previous failed virt-install can leave the qcow2 behind without a
    # libvirt domain. Treat that as stale provisioning state and clean it up.
    # If the domain exists, never delete its disk automatically.
    if os.path.exists(disk):
        domain_out = await _run_local_process(['virsh', 'dominfo', vm_name], timeout=15, check=False)
        if domain_out:
            raise RuntimeError(f'KVM VM already exists: {vm_name}')
        try:
            os.remove(disk)
            logger.warning('Removed stale KVM disk from previous failed deployment: %s', disk)
        except OSError as exc:
            raise RuntimeError(f'KVM stale disk exists and could not be removed: {disk}: {exc}')

    if not os.path.exists(base):
        tmp_base = base + '.part'
        try:
            await _run_local_process(['curl', '-fL', '--retry', '3', '--connect-timeout', '15', '-o', tmp_base, image_url], timeout=900)
            os.replace(tmp_base, base)
        except Exception:
            try:
                os.remove(tmp_base)
            except OSError:
                pass
            raise
    await _run_local_process(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', base, disk], timeout=120)
    await _run_local_process(['qemu-img', 'resize', disk, f'{disk_gb}G'], timeout=120)
    with open(user_data, 'w', encoding='utf-8') as fh:
        fh.write('''#cloud-config
ssh_pwauth: true
lock_passwd: false
disable_root: false
ssh_deletekeys: false
chpasswd:
  expire: false
  list: |
    root:__ROOT_PASSWORD__
package_reboot_if_required: false
packages:
  - curl
  - ca-certificates
  - qemu-guest-agent
write_files:
  - path: /etc/profile.d/voxelcloud-env.sh
    permissions: '0644'
    content: |
      export HOME=\"${HOME:-/root}\"
      export USER=\"${USER:-root}\"
      export LOGNAME=\"${LOGNAME:-root}\"
      export SHELL=\"${SHELL:-/bin/bash}\"
      export PATH=\"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}\"
  - path: /etc/environment
    permissions: '0644'
    content: |
      HOME=/root
      USER=root
      LOGNAME=root
      SHELL=/bin/bash
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  - path: /usr/local/sbin/voxelcloud-network-heal.sh
    permissions: '0755'
    content: |
      #!/bin/sh
      set +e
      IF=$(ip -o link show | awk -F': ' '$2 != "lo" {print $2; exit}')
      [ -n "$IF" ] || exit 0
      ip link set "$IF" up >/dev/null 2>&1 || true
      if command -v nmcli >/dev/null 2>&1; then nmcli device connect "$IF" >/dev/null 2>&1 || true
      elif command -v dhclient >/dev/null 2>&1; then dhclient -r "$IF" >/dev/null 2>&1 || true; dhclient -1 "$IF" >/dev/null 2>&1 || true
      elif command -v udhcpc >/dev/null 2>&1; then udhcpc -n -q -i "$IF" >/dev/null 2>&1 || true
      fi
      # Never hard-code the libvirt gateway: custom KVM_NETWORKs can use a
      # different subnet. DHCP should install the correct route/gateway.
      if command -v resolvectl >/dev/null 2>&1; then resolvectl flush-caches >/dev/null 2>&1 || true; fi
      if ! getent hosts cloudflare.com >/dev/null 2>&1; then printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > /etc/resolv.conf 2>/dev/null || true; fi
  - path: /etc/systemd/system/voxelcloud-network-heal.service
    permissions: '0644'
    content: |
      [Unit]
      Description=AxionHost guest network recovery
      Wants=network-online.target
      After=network-online.target
      [Service]
      Type=oneshot
      ExecStart=/usr/local/sbin/voxelcloud-network-heal.sh
      [Install]
      WantedBy=multi-user.target
runcmd:
  - >-
    bash -lc 'if ! command -v sshd >/dev/null 2>&1; then if command -v apt-get >/dev/null 2>&1; then DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server; elif command -v apk >/dev/null 2>&1; then apk add --no-cache openssh; elif command -v dnf >/dev/null 2>&1; then dnf install -y openssh-server; elif command -v yum >/dev/null 2>&1; then yum install -y openssh-server; elif command -v zypper >/dev/null 2>&1; then zypper --non-interactive install openssh-server; fi; fi'
  - >-
    bash -lc 'if command -v apt-get >/dev/null 2>&1; then DEBIAN_FRONTEND=noninteractive apt-get install -y qemu-guest-agent curl ca-certificates util-linux bash; elif command -v apk >/dev/null 2>&1; then apk add --no-cache qemu-guest-agent curl ca-certificates util-linux bash; elif command -v dnf >/dev/null 2>&1; then dnf install -y qemu-guest-agent curl ca-certificates util-linux bash; elif command -v yum >/dev/null 2>&1; then yum install -y qemu-guest-agent curl ca-certificates util-linux bash; elif command -v zypper >/dev/null 2>&1; then zypper --non-interactive install qemu-guest-agent curl ca-certificates util-linux bash; fi'
  - systemctl daemon-reload || true
  - systemctl enable --now ssh || systemctl enable --now sshd || true
  - systemctl enable --now qemu-guest-agent || true
  - systemctl enable --now voxelcloud-network-heal.service || true
'''.replace('__ROOT_PASSWORD__', root_password))
    with open(network_config, 'w', encoding='utf-8') as fh:
        fh.write(f'''version: 2
ethernets:
  voxelcloud0:
    match:
      macaddress: {vm_mac}
    dhcp4: true
    dhcp6: false
    optional: true
''')
    await ensure_kvm_network()
    base_args = ['virt-install', '--connect', 'qemu:///system', '--name', vm_name, '--memory', str(ram_gb * 1024), '--vcpus', str(cpu), '--disk', f'path={disk},format=qcow2,bus=virtio', '--network', f'network={KVM_NETWORK},model=virtio,mac={vm_mac}', '--osinfo', image.get('variant', 'generic'), '--import', '--graphics', 'none', '--noautoconsole', '--serial', 'pty', '--console', 'pty,target_type=serial', '--channel', 'unix,target_type=virtio,name=org.qemu.guest_agent.0', '--cloud-init', f'user-data={user_data},network-config={network_config}']
    if KVM_AUTOSTART:
        base_args.append('--autostart')

    # CPU model compatibility: never offer/attempt a named model that the host
    # cannot actually provide. This is especially important on nested KVM, where
    # an AMD model on an Intel L0/L1 host (or the reverse) can require features
    # such as svm/mmxext/sse4a that simply do not exist in the exposed CPU.
    requested_cpu = (cpu_model or KVM_CPU_MODE or 'auto').strip()
    requested_lower = requested_cpu.lower()
    requested_cpu_model = requested_cpu
    fallback_note = None
    if requested_lower in ('', 'auto', 'default'):
        # Restricted/nested KVM hosts may advertise host CPU models that require
        # unavailable mitigation features such as IBPB. Keep native modes first,
        # but always have a conservative CPU fallback.
        cpu_modes = ['host-passthrough', 'host-model', 'qemu64,ibpb=disable', 'qemu64', 'kvm64']
    elif requested_lower in ('host-model', 'host-passthrough', 'maximum'):
        cpu_modes = [requested_lower, 'host-model', 'qemu64,ibpb=disable', 'qemu64', 'kvm64']
    else:
        compat = await check_kvm_cpu_model_compatibility(requested_cpu)
        if not compat.get('compatible'):
            blockers = ', '.join(compat.get('blockers') or [])
            detail = f"Requested CPU `{requested_cpu}` is not compatible with this KVM host."
            if compat.get('vendor'):
                detail += f" Host reports vendor `{compat['vendor']}`."
            if blockers:
                detail += f" Missing/blocked features: `{blockers}`."
            if KVM_CPU_AUTO_FALLBACK:
                fallback_note = detail + " Automatically using conservative qemu64 CPU so the VPS can boot on restricted/nested KVM."
                cpu_modes = ['host-model', 'host-passthrough', 'qemu64,ibpb=disable', 'qemu64', 'kvm64']
            else:
                raise RuntimeError(detail + " Select Auto/Host Model or another usable processor.")
        else:
            cpu_modes = [requested_cpu, 'qemu64,ibpb=disable', 'qemu64', 'kvm64'] if requested_lower != 'qemu64' else ['qemu64,ibpb=disable', 'qemu64', 'kvm64']

    # Last-resort compatibility escape hatch for hosts missing CPU features
    # required by a named model (for example ibpb on nested virtualization).
    for _fallback_cpu in ('qemu64,ibpb=disable', 'qemu64', 'kvm64'):
        if _fallback_cpu not in cpu_modes:
            cpu_modes.append(_fallback_cpu)

    last_error = None
    selected_cpu = None
    creation_succeeded = False
    try:
        for cpu_mode in cpu_modes:
            args = list(base_args)
            if cpu_mode:
                args[args.index('--disk'):args.index('--disk')] = ['--cpu', cpu_mode]
            try:
                await _run_local_process(args, timeout=300)
                selected_cpu = cpu_mode or 'libvirt-default'
                creation_succeeded = True
                break
            except Exception as exc:
                last_error = exc
                # virt-install can leave a transient/defined domain after a
                # failed CPU validation. Remove only the failed definition;
                # never remove the qcow2 disk because the next attempt reuses it.
                try:
                    await _run_local_process(['virsh', 'destroy', vm_name], timeout=20, check=False)
                    await _run_local_process(['virsh', 'undefine', vm_name], timeout=20, check=False)
                except Exception:
                    pass
                continue
        else:
            raise RuntimeError(f'KVM VM creation failed with all compatible CPU modes. Last error: {last_error}')
    finally:
        for _tmp in (user_data, network_config):
            try:
                os.remove(_tmp)
            except OSError:
                pass
        # If virt-install could not create a domain, remove the per-VM disk so
        # the next deployment does not get stuck on "disk already exists".
        if not creation_succeeded and os.path.exists(disk):
            try:
                os.remove(disk)
                logger.warning('Removed failed KVM deployment disk: %s', disk)
            except OSError as cleanup_exc:
                logger.error('Could not remove failed KVM disk %s: %s', disk, cleanup_exc)
    # Cloud-init may install qemu-guest-agent only after the guest network is
    # ready. A 1-second QGA check is therefore too early and can make a healthy
    # VM look broken. Retry for a bounded period and NEVER delete/rollback the VM
    # merely because QGA is still booting. SSH repair can continue in background.
    network_status = {}
    qga_ready = False
    qga_error = ''
    try:
        # DHCP lease and QGA are independent. Get the lease first, then wait for
        # QGA in the background window. A missing QGA must never destroy a usable VM.
        nets = await wait_for_kvm_network(vm_name, timeout=min(max(KVM_GUEST_NETWORK_TIMEOUT, 45), 120))
        # No DHCP lease is a real network problem; do one safe host-side rescue
        # before declaring the network unavailable. This does not depend on QGA.
        if not nets and KVM_NETWORK_REPAIR_ON_START:
            try:
                nets = await asyncio.wait_for(kvm_network_rescue(vm_name, timeout=60), timeout=75)
            except Exception as rescue_exc:
                logger.warning('KVM network rescue failed for %s: %s', vm_name, rescue_exc)
        qga_ready = await wait_for_kvm_guest_agent(vm_name, timeout=min(max(KVM_QGA_WAIT_TIMEOUT, 30), 180))
        if not qga_ready:
            qga_error = 'QEMU Guest Agent is still booting or not installed in the guest.'
        if not nets and qga_ready:
            try:
                await asyncio.wait_for(kvm_guest_network_doctor(vm_name, repair=True), timeout=25)
                nets = await wait_for_kvm_network(vm_name, timeout=30)
            except asyncio.TimeoutError:
                logger.warning('KVM guest network repair timed out for %s; VM remains running.', vm_name)
            except Exception as repair_exc:
                logger.warning('KVM guest network repair failed for %s: %s', vm_name, repair_exc)
        network_status = {'ipv4': nets, 'ready': bool(nets), 'qga_ready': qga_ready, 'qga_pending': not qga_ready, 'qga_error': qga_error[-500:] if qga_error else None}
    except Exception as exc:
        network_status = {'ipv4': {}, 'ready': False, 'qga_ready': qga_ready, 'qga_pending': not qga_ready, 'error': str(exc)[:1000]}
    return {'backend': 'kvm', 'disk': disk, 'image': image_ref, 'image_url': image_url, 'cpu_model': selected_cpu, 'requested_cpu_model': requested_cpu_model, 'cpu_fallback': fallback_note, 'network': KVM_NETWORK, 'mac_address': vm_mac, 'network_mode': KVM_NETWORK, 'network_status': network_status}


async def get_kvm_networks(vm_name: str) -> Dict[str, str]:
    """Discover KVM guest IPv4 addresses, preferring host-side DHCP leases so QGA is not required."""
    result: Dict[str, str] = {}
    # First use libvirt's own DHCP database. This works even when QEMU Guest
    # Agent is still booting/unavailable.
    try:
        ifaces = await _run_local_process(['virsh', '-c', 'qemu:///system', 'domiflist', vm_name], timeout=15, check=False)
        macs = {line.split()[4].lower() for line in ifaces.splitlines()[2:] if len(line.split()) >= 5 and re.fullmatch(r'[0-9a-fA-F:]{17}', line.split()[4])}
        leases = await _run_local_process(['virsh', '-c', 'qemu:///system', 'net-dhcp-leases', KVM_NETWORK], timeout=15, check=False)
        for line in leases.splitlines():
            low = line.lower()
            if macs and not any(mac in low for mac in macs):
                continue
            for token in line.split():
                ip = token.split('/')[0]
                if re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}', ip) and not ip.startswith('127.'):
                    result['eth0'] = ip
                    break
            if result:
                return result
    except Exception:
        pass
    # QGA is second choice; it gives the most accurate interface information.
    try:
        out = await _run_local_process(['virsh', '-c', 'qemu:///system', 'domifaddr', vm_name, '--source', 'agent'], timeout=10, check=False)
        for line in out.splitlines():
            parts = line.split()
            for token in parts:
                ip = token.split('/')[0]
                if re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}', ip) and not ip.startswith('127.'):
                    iface = parts[0] if parts else 'eth0'
                    result[iface] = ip
    except Exception:
        pass
    if result:
        return result
    try:
        out = await _run_local_process(['virsh', '-c', 'qemu:///system', 'domifaddr', vm_name, '--source', 'lease'], timeout=15, check=False)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                for token in parts[3:]:
                    ip = token.split('/')[0]
                    if re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}', ip) and not ip.startswith('127.'):
                        result[parts[0]] = ip
                        break
    except Exception:
        pass
    if result:
        return result
    # Final host-side fallbacks: ARP/neighbour tables can reveal a guest IP
    # even when dnsmasq has not persisted a lease yet and QGA is unavailable.
    try:
        ifaces = await _run_local_process(['virsh', '-c', 'qemu:///system', 'domiflist', vm_name], timeout=10, check=False)
        macs = [line.split()[4].lower() for line in ifaces.splitlines()[2:] if len(line.split()) >= 5 and re.fullmatch(r'[0-9a-fA-F:]{17}', line.split()[4])]
        if macs:
            arp = await _run_local_process(['ip', '-4', 'neigh', 'show'], timeout=10, check=False)
            for line in arp.splitlines():
                low = line.lower()
                if any(mac in low for mac in macs):
                    m = re.search(r'^(\d{1,3}(?:\.\d{1,3}){3})\s+', line)
                    if m and m.group(1) != '127.0.0.1':
                        result['eth0'] = m.group(1)
                        return result
    except Exception:
        pass
    return result

async def kvm_network_rescue(vm_name: str, timeout: int = 60) -> Dict[str, str]:
    """Repair host-side libvirt networking without destroying/restarting a guest.

    A forced destroy can corrupt guest state and usually does not fix a missing
    DHCP lease if the upstream host blocks nested networking. This routine
    validates the system libvirt network, ensures it is active/autostarted, then
    checks the VM NIC/lease/neighbour table. It preserves the VM and disk.
    """
    try:
        await ensure_kvm_network()
    except Exception as exc:
        logger.warning('KVM network ensure failed for %s: %s', vm_name, exc)
    try:
        state = await _run_local_process(['virsh', '-c', 'qemu:///system', 'domstate', vm_name], timeout=10, check=False)
        if 'running' not in state.lower():
            await _run_local_process(['virsh', '-c', 'qemu:///system', 'start', vm_name], timeout=45, check=False)
    except Exception as exc:
        logger.warning('KVM network rescue could not start %s: %s', vm_name, exc)
    # Recheck leases for the requested interval; don't confuse missing DHCP
    # with QGA being offline and don't silently reboot the user's VM.
    return await wait_for_kvm_network(vm_name, timeout)

async def wait_for_kvm_network(vm_name: str, timeout: int = 45) -> Dict[str, str]:
    """Wait briefly for DHCP/guest-agent networking after first boot."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        nets = await get_kvm_networks(vm_name)
        if nets:
            return nets
        await asyncio.sleep(2)
    return await get_kvm_networks(vm_name)



# LXC/Incus project resolver. Older code assumed every instance lived in the
# `default` project; installations that use named projects then reported
# "Instance not found" and retried SSH repair forever. Resolve by instance name
# and only add --project when the local CLI confirms a non-default project.
async def _lxc_find_instance_project(instance_name: str) -> Optional[str]:
    if not instance_name or not shutil.which(LXC_CMD):
        return None
    try:
        raw = await _run_local_process([LXC_CMD, 'list', '--all-projects', '--format=json'], timeout=20, check=False)
        items = json.loads(raw) if raw else []
        if isinstance(items, list):
            matches = [x for x in items if str(x.get('name', '')) == instance_name]
            if matches:
                # Prefer a running instance if duplicate names are present in
                # different projects; never silently choose an arbitrary one.
                matches.sort(key=lambda x: 0 if str(x.get('status', '')).lower() == 'running' else 1)
                projects = {str(x.get('project') or 'default') for x in matches}
                if len(projects) == 1:
                    return next(iter(projects))
                logger.warning('LXC instance name %s exists in multiple projects: %s', instance_name, sorted(projects))
                return str(matches[0].get('project') or 'default')
    except Exception as exc:
        logger.debug('LXC all-project lookup unavailable: %s', exc)
    # Compatibility fallback for CLI versions that do not support --all-projects.
    try:
        raw = await _run_local_process([LXC_CMD, 'project', 'list', '--format=json'], timeout=15, check=False)
        projects = json.loads(raw) if raw else []
        names = [str(x.get('name')) for x in projects if isinstance(x, dict) and x.get('name')]
        if not names:
            names = ['default']
        for project in names:
            args = [LXC_CMD, '--project', project, 'list', '--format=json']
            listed = await _run_local_process(args, timeout=15, check=False)
            items = json.loads(listed) if listed else []
            if isinstance(items, list) and any(str(x.get('name', '')) == instance_name for x in items):
                return project
    except Exception as exc:
        logger.debug('LXC project-by-project lookup unavailable: %s', exc)
    return None


async def execute_lxc(container_name: str, command: str, timeout=120, node_id: Optional[int] = None):
    if container_name and get_vps_backend(container_name) == 'kvm':
        return await execute_kvm(container_name, command, node_id or find_node_id_for_container(container_name))
    if node_id is None:
        node_id = find_node_id_for_container(container_name)
    node = get_node(node_id)

    if not node:
        raise Exception(f"Node {node_id} not found")

    # REMOTE_NODE_ONLY is a hard routing policy. All LXC operations, including
    # SSHX/guest exec paths, must use the configured remote node.
    if REMOTE_NODE_ONLY and bool(node.get('is_local')):
        requested_node_id = int(node_id)
        node_id = _preferred_deployment_node_id()
        node = get_node(node_id)
        if not node or bool(node.get('is_local')):
            raise RuntimeError('Remote-only mode is enabled, but no remote VPS node is configured.')
        logger.warning('REMOTE_NODE_ONLY redirected LXC operation from local node_id=%s to remote node_id=%s', requested_node_id, node_id)

    full_command = f"{LXC_CMD} {command}"

    if node['is_local']:
        try:
            cmd = shlex.split(full_command)
            # Only resolve instance-targeted commands. Avoid changing general
            # project/list/storage commands and preserve the user's arguments.
            if cmd and cmd[0] == LXC_CMD and len(cmd) >= 3:
                action = cmd[1]
                target = None
                # Most instance commands put the instance immediately after
                # the action. `config` has a subcommand before its instance.
                if action in ('exec', 'info', 'start', 'stop', 'restart',
                              'delete', 'snapshot'):
                    target = cmd[2]
                elif action in ('copy', 'move'):
                    target = cmd[2]  # source instance
                elif action == 'config' and len(cmd) >= 4:
                    subcommand = cmd[2]
                    if subcommand in ('set', 'unset', 'show', 'edit', 'get'):
                        target = cmd[3]
                    elif subcommand == 'device' and len(cmd) >= 5:
                        device_action = cmd[3]
                        if device_action in ('add', 'remove', 'set', 'unset', 'get'):
                            target = cmd[4]
                if target and not target.startswith('-'):
                    project = await _lxc_find_instance_project(target)
                    if project is None:
                        raise RuntimeError(
                            f'LXC/Incus instance `{target}` was not found in any visible project. '
                            'Check `lxc list --all-projects` and the VPS database mapping; '
                            'no container was modified.'
                        )
                    cmd = [LXC_CMD, '--project', project] + cmd[1:]
                    full_command = shlex.join(cmd)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise asyncio.TimeoutError(f"Command timed out after {timeout} seconds")

            if proc.returncode != 0:
                error = stderr.decode().strip() if stderr else "Command failed with no error output"
                raise Exception(f"Local LXC command failed: {error}\nCommand: {full_command}")
            return stdout.decode().strip() if stdout else True
        except asyncio.TimeoutError as te:
            logger.error(f"LXC command timed out: {full_command} - {str(te)}")
            raise
        except Exception as e:
            logger.error(f"LXC Error: {full_command} - {str(e)}")
            raise
    else:
        url = f"{node['url']}/api/execute"
        data = {"command": full_command}
        params = {"api_key": node["api_key"]}
        try:
            response = await http_request('POST', url, json=data, params=params, timeout=timeout)
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_detail = response.json()
                    if 'detail' in error_detail:
                        error_msg = error_detail['detail']
                    elif 'error' in error_detail:
                        error_msg = error_detail['error']
                    elif 'stderr' in error_detail:
                        error_msg = error_detail['stderr']
                except:
                    pass
                raise Exception(f"Remote execution failed on {node['name']}: {error_msg}\nCommand: {full_command}")
            res = response.json()
            if res.get("returncode", 1) != 0:
                stderr = res.get("stderr", "Command failed")
                raise Exception(f"Remote LXC command failed on {node['name']}: {stderr}\nCommand: {full_command}")
            return res.get("stdout", True)
        except requests.exceptions.ConnectionError:
            raise Exception(f"Node {node['name']} is unreachable (network error).")
        except requests.exceptions.Timeout:
            raise Exception(f"Remote execution timed out on {node['name']} (timeout after {timeout}s)")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Remote execution failed on {node['name']}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error executing command on node {node['name']}: {str(e)}")
            raise

# Apply LXC config
async def apply_lxc_config(container_name: str, node_id: int):
    """Apply a secure baseline to a newly created VPS.

    Old versions made every VPS privileged, unconfined and device-unrestricted.
    That defeats container isolation. New VPS are unprivileged by default.
    Set VPS_PRIVILEGED=true only when a trusted workload genuinely requires it.
    """
    try:
        await execute_lxc(
            container_name,
            f"config set {container_name} security.privileged {'true' if VPS_PRIVILEGED else 'false'}",
            node_id=node_id,
        )
        docker_ready = VPS_DOCKER_READY or VPS_NESTING
        await execute_lxc(
            container_name,
            f"config set {container_name} security.nesting {'true' if docker_ready else 'false'}",
            node_id=node_id,
        )
        await execute_lxc(
            container_name,
            f"config set {container_name} boot.autostart true",
            node_id=node_id,
        )
        if docker_ready:
            # Incus documents nesting=true for Docker-in-container. These
            # interceptions are useful for common nested Docker workloads.
            await execute_lxc(container_name, f"config set {container_name} security.syscalls.intercept.mknod true", node_id=node_id)
            await execute_lxc(container_name, f"config set {container_name} security.syscalls.intercept.setxattr true", node_id=node_id)
            if VPS_DOCKER_KERNEL_MODULES:
                await execute_lxc(container_name, f"config set {container_name} linux.kernel_modules {shlex.quote(VPS_DOCKER_KERNEL_MODULES)}", node_id=node_id)
        logger.info(
            "Applied secure LXC baseline to %s (privileged=%s, nesting=%s)",
            container_name, VPS_PRIVILEGED, VPS_NESTING
        )
    except Exception as e:
        logger.error(f"Failed to apply LXC security baseline to {container_name}: {e}")
        raise

# Apply internal permissions
async def apply_internal_permissions(container_name: str, node_id: int):
    """Apply only low-risk guest tuning; do not weaken host/container isolation."""
    try:
        await asyncio.sleep(3)
        commands = [
            "mkdir -p /etc/sysctl.d/",
            "cat > /etc/sysctl.d/99-axionhost-guest.conf <<'EOF_AXION'\nfs.inotify.max_user_watches=524288\nfs.inotify.max_user_instances=8192\nfs.inotify.max_queued_events=32768\nEOF_AXION",
            "sysctl --system >/dev/null 2>&1 || true"
        ]
        for cmd in commands:
            try:
                await execute_lxc(container_name, f"exec {container_name} -- sh -c {shlex.quote(cmd)}", node_id=node_id)
            except Exception as cmd_error:
                logger.warning(f"Guest tuning skipped in {container_name}: {cmd_error}")
        logger.info(f"Guest tuning applied to {container_name}")
    except Exception as e:
        logger.error(f"Failed to apply guest tuning to {container_name}: {e}")

# Get or create VPS role
async def get_or_create_vps_role(guild):
    global VPS_USER_ROLE_ID

    me = guild.me
    if not me or not me.guild_permissions.manage_roles:
        return None

    role_name = f"{BOT_NAME} VPS User"

    # Try cached role
    if VPS_USER_ROLE_ID:
        role = guild.get_role(VPS_USER_ROLE_ID)
        if role and role < me.top_role:
            return role
        VPS_USER_ROLE_ID = None

    # Find by name
    role = discord.utils.get(guild.roles, name=role_name)
    if role:
        if role >= me.top_role:
            try:
                await role.delete(reason="Role above bot, recreating")
            except discord.Forbidden:
                return None
            role = None
        else:
            VPS_USER_ROLE_ID = role.id
            return role

    # Create safely below bot
    try:
        role = await guild.create_role(
            name=role_name,
            color=discord.Color.dark_purple(),
            permissions=discord.Permissions.none(),
            reason=f"{BOT_NAME} VPS User role"
        )
        await role.edit(position=me.top_role.position - 1)
        VPS_USER_ROLE_ID = role.id
        logger.info(f"Created VPS role: {role.id}")
        return role
    except Exception as e:
        logger.error(f"Failed to create VPS role: {e}")
        return None

# Host resource functions
def get_host_cpu_usage():
    """Get host CPU usage - cross-platform compatible"""
    try:
        import platform
        system = platform.system()
        
        if system == "Windows":
            # Windows: Use wmic or psutil as fallback
            try:
                import psutil
                return psutil.cpu_percent(interval=1)
            except ImportError:
                # Fallback for Windows without psutil
                try:
                    result = subprocess.run(['wmic', 'os', 'get', 'TotalVisibleMemorySize'], 
                                          capture_output=True, text=True, timeout=5)
                    return 0.0  # Default value on Windows
                except:
                    return 0.0
        else:
            # Linux/Unix: Use mpstat or top
            if shutil.which("mpstat"):
                result = subprocess.run(['mpstat', '1', '1'], capture_output=True, text=True, timeout=10)
                output = result.stdout
                for line in output.split('\n'):
                    if 'all' in line and '%' in line:
                        parts = line.split()
                        idle = float(parts[-1])
                        return 100.0 - idle
            else:
                result = subprocess.run(['top', '-bn1'], capture_output=True, text=True, timeout=10)
                output = result.stdout
                for line in output.split('\n'):
                    if '%Cpu(s):' in line:
                        # Parse CPU line - format: %Cpu(s): us,sy,ni,id,wa,hi,si,st
                        cpu_data = line.split('%Cpu(s):')[1].strip()
                        parts = []
                        for item in cpu_data.split(','):
                            val = item.split()[0].strip()
                            try:
                                parts.append(float(val))
                            except ValueError:
                                parts.append(0.0)
                        
                        if len(parts) >= 8:
                            us = parts[0]
                            sy = parts[1]
                            ni = parts[2]
                            id_ = parts[3]
                            wa = parts[4]
                            hi = parts[5]
                            si = parts[6]
                            st = parts[7]
                            usage = us + sy + ni + wa + hi + si + st
                            return usage
            return 0.0
    except Exception as e:
        logger.debug(f"Error getting CPU usage: {e}")
        return 0.0

def get_host_ram_usage():
    """Get host RAM usage - cross-platform compatible"""
    try:
        import platform
        system = platform.system()
        
        if system == "Windows":
            # Windows: Use psutil or wmic
            try:
                import psutil
                mem = psutil.virtual_memory()
                return mem.percent
            except ImportError:
                # Fallback for Windows without psutil
                try:
                    result = subprocess.run(['wmic', 'OS', 'get', 'TotalVisibleMemorySize,FreePhysicalMemory'], 
                                          capture_output=True, text=True, timeout=5)
                    lines = result.stdout.strip().split('\n')
                    if len(lines) > 1:
                        values = lines[1].split()
                        if len(values) >= 2:
                            total = int(values[0])
                            free = int(values[1])
                            used = total - free
                            return (used / total * 100) if total > 0 else 0.0
                except:
                    pass
                return 0.0
        else:
            # Linux/Unix: Use free command
            result = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=10)
            lines = result.stdout.splitlines()
            if len(lines) > 1:
                mem = lines[1].split()
                total = int(mem[1])
                used = int(mem[2])
                return (used / total * 100) if total > 0 else 0.0
            return 0.0
    except Exception as e:
        logger.debug(f"Error getting RAM usage: {e}")
        return 0.0

_expiration_warnings_sent = set()

def check_vps_expiration():
    """Check and auto-suspend expired VPS from the monitor thread."""
    global bot, _expiration_warnings_sent
    try:
        warned_users = _expiration_warnings_sent
        
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps.get('expiration_date'):
                    if vps.get('whitelisted', False):
                        continue
                    try:
                        expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                    except (TypeError, ValueError):
                        logger.warning(f"Invalid expiration date for {vps.get('container_name')}: {vps.get('expiration_date')}")
                        continue
                    days_remaining = (expiration_dt - datetime.now()).days
                    hours_remaining = ((expiration_dt - datetime.now()).total_seconds() / 3600)
                    
                    container_name = vps['container_name']
                    node_id = vps.get('node_id', 1)
                    
                    # Auto-suspend if expired
                    if hours_remaining <= 0:
                        if not vps.get('suspended', False):
                            try:
                                # Suspend the VPS
                                run_on_bot_loop(execute_lxc(container_name, f"stop {container_name}", node_id=node_id))
                                vps['status'] = 'stopped'
                                vps['suspended'] = True
                                vps.setdefault('suspension_history', []).append({
                                    'time': datetime.now().isoformat(),
                                    'reason': f'Auto-suspended due to VPS expiration on {expiration_dt.strftime("%Y-%m-%d")}',
                                    'by': 'Expiration Monitor'
                                })
                                save_vps_data_immediate()
                                logger.warning(f"VPS {container_name} auto-suspended due to expiration")
                                
                                # Notify owner
                                try:
                                    owner = run_on_bot_loop(bot.fetch_user(int(user_id)))
                                    dm_embed = create_error_embed("🔴 VPS Expired and Suspended",
                                        f"Your VPS `{container_name}` has expired and been suspended.\n\n"
                                        f"**Expiration Date:** {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                        f"Contact an admin to renew your VPS.")
                                    run_on_bot_loop(owner.send(embed=dm_embed))
                                except Exception as e:
                                    logger.debug(f"Failed to notify user {user_id}: {e}")
                            except Exception as e:
                                logger.error(f"Failed to auto-suspend VPS {container_name}: {e}")
                    
                    # Send warning if expiring soon
                    elif 0 < hours_remaining <= (EXPIRATION_WARNING_DAYS * 24):
                        warning_key = f"{container_name}:{vps.get('expiration_date')}"
                        if warning_key not in warned_users:
                            try:
                                owner = run_on_bot_loop(bot.fetch_user(int(user_id)))
                                dm_embed = create_warning_embed("⏰ VPS Expiring Soon",
                                    f"Your VPS `{container_name}` will expire in {days_remaining} day(s)!\n\n"
                                    f"**Expiration Date:** {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                    f"Contact an admin to renew your VPS before it's automatically suspended.")
                                run_on_bot_loop(owner.send(embed=dm_embed))
                                warned_users.add(warning_key)
                                logger.info(f"Sent expiration warning to user {user_id}")
                            except Exception as e:
                                logger.debug(f"Failed to notify user {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error in VPS expiration check: {e}")

def resource_monitor():
    global resource_monitor_active
    last_expiration_check = time.time()
    expiration_check_interval = 3600  # Check every hour
    
    while True:
        try:
            if not resource_monitor_active:
                time.sleep(10)
                continue
            # Check VPS expiration every hour
            if time.time() - last_expiration_check > expiration_check_interval:
                check_vps_expiration()
                last_expiration_check = time.time()
            
            nodes = get_nodes()
            for node in nodes:
                # Only monitor LOCAL nodes - skip remote nodes to avoid "No route to host" errors
                if node['is_local']:
                    # Resource monitor runs in a background thread. Do not call
                    # asyncio.run() here because it creates/closes a temporary
                    # event loop while discord.py is running on its own loop.
                    # The local host metrics are synchronous, so read them directly.
                    stats = {
                        'cpu': get_host_cpu_usage(),
                        'ram': get_host_ram_usage(),
                        'disk': get_host_disk_usage(),
                    }
                    cpu = stats['cpu']
                    ram = stats['ram']
                    logger.info(f"Node {node['name']}: CPU {cpu:.1f}%, RAM {ram:.1f}%")
                    if cpu > CPU_THRESHOLD or ram > RAM_THRESHOLD:
                        logger.warning(f"Node {node['name']} exceeded thresholds (CPU: {CPU_THRESHOLD}%, RAM: {RAM_THRESHOLD}%). Manual intervention required.")
                else:
                    # Remote nodes - skip monitoring to avoid connection errors
                    logger.debug(f"Skipping remote node {node['name']} - remote nodes monitored on-demand only")
            
            time.sleep(60)
        except Exception as e:
            logger.error(f"Error in resource monitor: {e}")
            time.sleep(60)

# Resource monitor is started from on_ready after the Discord loop exists.
monitor_thread = None

# Per-VPS operation locks prevent duplicate Pinggy/SSHX/Cloudflare operations
# when a user taps a Discord button multiple times.
_tunnel_locks: Dict[str, asyncio.Lock] = {}

def _get_tunnel_lock(vps_name: str, purpose: str = '') -> asyncio.Lock:
    """Return one asyncio lock per VPS + connection feature.

    Older builds accepted one argument while newer tunnel code passed a second
    purpose argument, causing a runtime TypeError during Pinggy reconnect.
    """
    key = f"{str(purpose or 'generic').strip().lower()}:{str(vps_name or '').strip().lower()}"
    lock = _tunnel_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _tunnel_locks[key] = lock
    return lock

# Container stats with multi-node
async def get_container_stats(container_name: str, node_id: Optional[int] = None) -> Dict:
    if node_id is None:
        node_id = find_node_id_for_container(container_name)
    node = get_node(node_id)
    if get_vps_backend(container_name) == 'kvm' and node and node.get('is_local'):
        try:
            info = await _run_local_process(['virsh', 'dominfo', container_name], timeout=20)
            status = 'running' if re.search(r'^State:\s*running', info, re.I | re.M) else 'stopped'
            cpu_match = re.search(r'^CPU\(s\):\s*(\d+)', info, re.I | re.M)
            mem_match = re.search(r'^Max memory:\s*(\d+) KiB', info, re.I | re.M)
            cpu_count = int(cpu_match.group(1)) if cpu_match else 0
            mem_kib = int(mem_match.group(1)) if mem_match else 0
            disk = 'VM disk (use `vps-stats`/guest df for filesystem usage)'
            return {'status': status, 'cpu': 0.0, 'ram': {'used': 0, 'total': round(mem_kib / 1024), 'pct': 0.0}, 'disk': disk, 'uptime': 'VM uptime available from guest OS'}
        except Exception as exc:
            logger.debug('KVM stats failed for %s: %s', container_name, exc)
            return {'status': 'unknown', 'cpu': 0.0, 'ram': {'used': 0, 'total': 0, 'pct': 0.0}, 'disk': 'Unknown', 'uptime': 'Unknown'}
    if node['is_local']:
        status = await get_container_status_local(container_name)
        cpu = await get_container_cpu_pct_local(container_name)
        ram = await get_container_ram_local(container_name)
        disk = await get_container_disk_local(container_name)
        uptime = await get_container_uptime_local(container_name)
        return {"status": status, "cpu": cpu, "ram": ram, "disk": disk, "uptime": uptime}
    else:
        # Remote node - handle unreachable nodes gracefully without spamming logs
        url = f"{node['url']}/api/get_container_stats"
        data = {"container": container_name}
        params = {"api_key": node["api_key"]}
        try:
            response = await http_request('POST', url, json=data, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            # Remote node unreachable - return graceful defaults
            logger.debug(f"Remote node {node['name']} unreachable for container {container_name}")
            return {"status": "unknown", "cpu": 0.0, "ram": {"used": 0, "total": 0, "pct": 0.0}, "disk": "Unknown", "uptime": "Unknown"}
        except Exception as e:
            logger.debug(f"Failed to get container stats from remote node {node['name']}: {e}")
            return {"status": "unknown", "cpu": 0.0, "ram": {"used": 0, "total": 0, "pct": 0.0}, "disk": "Unknown", "uptime": "Unknown"}

async def get_container_status_local(container_name: str):
    try:
        if get_vps_backend(container_name) == 'kvm':
            out = await execute_kvm(container_name, f'info {container_name}', find_node_id_for_container(container_name))
            m = re.search(r'^State:\s*(.+)$', str(out), re.I | re.M)
            return m.group(1).strip().lower() if m else 'unknown'
        proc = await asyncio.create_subprocess_exec(
            LXC_CMD, "info", container_name,   # ← was: "lxc"
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        for line in output.splitlines():
            if line.startswith("Status: "):
                return line.split(": ", 1)[1].strip().lower()
        return "unknown"
    except Exception:
        return "unknown"

async def get_container_cpu_pct_local(container_name: str):
    try:
        if get_vps_backend(container_name) == 'kvm':
            out = await _run_local_process(['virsh', 'domstats', container_name, '--cpu-total'], timeout=20)
            m = re.search(r'cpu\.time=(\d+)', out)
            return 0.0 if not m else 0.0
        proc = await asyncio.create_subprocess_exec(
            LXC_CMD, "exec", container_name, "--", "top", "-bn1",   # ← was: "lxc"
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        for line in output.splitlines():
            if '%Cpu(s):' in line:
                # Parse CPU line - format: %Cpu(s): us,sy,ni,id,wa,hi,si,st
                # Remove label and split by commas
                cpu_data = line.split('%Cpu(s):')[1].strip()
                parts = []
                for item in cpu_data.split(','):
                    # Extract number before the percentage/label
                    val = item.split()[0].strip()
                    try:
                        parts.append(float(val))
                    except ValueError:
                        parts.append(0.0)
                
                if len(parts) >= 8:
                    us = parts[0]  # user
                    sy = parts[1]  # system
                    ni = parts[2]  # nice
                    id_ = parts[3] # idle
                    wa = parts[4]  # wait
                    hi = parts[5]  # hardware interrupt
                    si = parts[6]  # software interrupt
                    st = parts[7]  # steal
                    return us + sy + ni + wa + hi + si + st
        return 0.0
    except Exception as e:
        logger.error(f"Error getting container CPU for {container_name}: {e}")
        return 0.0

async def get_container_ram_local(container_name: str):
    try:
        if get_vps_backend(container_name) == 'kvm':
            out = await _run_local_process(['virsh', 'dominfo', container_name], timeout=20)
            m = re.search(r'^Max memory:\s*(\d+) KiB', out, re.I | re.M)
            total = int(m.group(1)) // 1024 if m else 0
            return {'used': 0, 'total': total, 'pct': 0.0}
        proc = await asyncio.create_subprocess_exec(
            LXC_CMD, "exec", container_name, "--", "free", "-m",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            pct = (used / total * 100) if total > 0 else 0.0
            return {'used': used, 'total': total, 'pct': pct}
        return {'used': 0, 'total': 0, 'pct': 0.0}
    except Exception as e:
        logger.error(f"Error getting RAM for {container_name}: {e}")
        return {'used': 0, 'total': 0, 'pct': 0.0}

async def get_container_disk_local(container_name: str):
    try:
        if get_vps_backend(container_name) == 'kvm':
            path = await _kvm_disk_path(container_name)
            if path and os.path.exists(path):
                size = os.path.getsize(path)
                return f'{size / (1024**3):.1f} GiB qcow2 host file'
            return 'VM disk'
        proc = await asyncio.create_subprocess_exec(
            LXC_CMD, "exec", container_name, "--", "df", "-h", "/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        for line in lines:
            if '/dev/' in line and ' /' in line:
                parts = line.split()
                if len(parts) >= 5:
                    used = parts[2]
                    size = parts[1]
                    perc = parts[4]
                    return f"{used}/{size} ({perc})"
        return "Unknown"
    except Exception:
        return "Unknown"

async def get_container_uptime_local(container_name: str):
    try:
        if get_vps_backend(container_name) == 'kvm':
            return 'Guest uptime is reported by the VM OS.'
        proc = await asyncio.create_subprocess_exec(
            LXC_CMD, "exec", container_name, "--", "uptime",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip() if stdout else "Unknown"
    except Exception:
        return "Unknown"

async def get_container_status(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return stats['status']

async def get_container_cpu(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return f"{stats['cpu']:.1f}%"

async def get_container_cpu_pct(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return stats['cpu']

async def get_container_memory(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    ram = stats['ram']
    return f"{ram['used']}/{ram['total']} MB ({ram['pct']:.1f}%)"

async def get_container_ram_pct(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return stats['ram']['pct']

async def get_container_networks(container_name: str, node_id: Optional[int] = None) -> Dict[str, str]:
    """Get all network interfaces and their IPs from a container using ip addr command"""
    try:
        if node_id is None:
            node_id = find_node_id_for_container(container_name)
        
        # First attempt: Use simple ip addr show command
        proc = await asyncio.create_subprocess_exec(
            LXC_CMD, "exec", container_name, "--", "ip", "addr", "show",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        networks = {}
        
        if proc.returncode == 0:
            output = stdout.decode().strip()
            
            # Parse ip addr show output
            # Format: 
            # 2: eth0: <BROADCAST,RUNNING> mtu 1500
            #     inet 10.0.0.10/24 brd 10.0.0.255 scope global eth0
            
            lines = output.split('\n')
            current_interface = None
            
            for line in lines:
                # Check for interface line (starts with number and interface name)
                if line and line[0].isdigit():
                    # Extract interface name from line like "2: eth0: <BROADCAST>"
                    parts = line.split(':')
                    if len(parts) >= 2:
                        current_interface = parts[1].strip()
                
                # Check for inet line (IPv4 address)
                elif 'inet ' in line and current_interface:
                    # Extract IP from line like "    inet 10.0.0.10/24 brd 10.0.0.255 scope global eth0"
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[0] == 'inet':
                        ip_with_cidr = parts[1]
                        ip = ip_with_cidr.split('/')[0]
                        
                        # Skip loopback
                        if ip != "127.0.0.1" and current_interface != "lo":
                            networks[current_interface] = ip
        else:
            logger.warning(f"Failed to get network info for {container_name}: {stderr.decode()}")
        
        if networks:
            logger.info(f"Found {len(networks)} network interfaces on {container_name}: {networks}")
        else:
            logger.warning(f"No usable network interfaces found for {container_name}")
        
        return networks
    except Exception as e:
        logger.error(f"Error getting networks for {container_name}: {e}")
        return {}

async def get_container_disk(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return stats['disk']

async def get_container_uptime(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return stats['uptime']

def get_uptime():
    """Get system uptime - cross-platform compatible"""
    try:
        import platform
        system = platform.system()
        
        if system == "Windows":
            try:
                result = subprocess.run(['net', 'statistics', 'server'], 
                                      capture_output=True, text=True, timeout=5)
                output = result.stdout
                for line in output.split('\n'):
                    if 'Statistics since' in line:
                        return line.strip()
                return "Unknown"
            except:
                # Fallback: use wmic
                try:
                    result = subprocess.run(['wmic', 'os', 'get', 'lastbootuptime'], 
                                          capture_output=True, text=True, timeout=5)
                    return result.stdout.strip() if result.stdout else "Unknown"
                except:
                    return "Unknown"
        else:
            # Linux/Unix: Use uptime command
            result = subprocess.run(['uptime'], capture_output=True, text=True, timeout=5)
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f"Error getting uptime: {e}")
        return "Unknown"

# Try to detect default storage pool or use common defaults
def get_default_storage_pool():
    try:
        result = subprocess.run([LXC_CMD, 'storage', 'list', '--format', 'csv'], 
                              capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')
        if lines and lines[0]:
            # Get first storage pool
            return lines[0].split(',')[0]
    except:
        pass
    return "default"  # Fallback to 'default'

DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', get_default_storage_pool())

# Bot events
async def resource_limit_watchdog_task():
    """Monitor FD/cgroup PID pressure; systemd must own the actual limit changes."""
    while True:
        try:
            import resource
            soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
            open_files = 0
            try:
                open_files = len(os.listdir(f'/proc/{os.getpid()}/fd'))
            except Exception:
                pass
            if soft not in (0, resource.RLIM_INFINITY) and open_files >= int(soft * 0.80):
                logger.warning('Resource watchdog: %d open FDs vs soft limit %s.', open_files, soft)
            pmax = None
            try:
                cg = Path(f'/proc/{os.getpid()}/cgroup').read_text(errors='ignore')
                for line in cg.splitlines():
                    if '::' in line:
                        rel=line.split('::',1)[1].strip('/')
                        candidate=Path('/sys/fs/cgroup')/rel/'pids.max'
                        if candidate.exists():
                            pmax=candidate.read_text().strip(); break
            except Exception:
                pass
            if pmax and pmax.isdigit():
                threads=len(threading.enumerate())
                if threads >= max(1,int(pmax)*0.80):
                    logger.warning('Resource watchdog: %d Python threads vs cgroup pids.max=%s.', threads, pmax)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug('Resource watchdog iteration failed.', exc_info=True)
        await asyncio.sleep(60)

@bot.event
async def on_ready():
    global vps_data, admin_data, _vps_data_loaded_once
    logger.info(f'{bot.user} has connected to Discord!')
    # Process startup already loaded persistent state from the fixed SQLite
    # database. Do not replace live in-memory state on every Discord gateway
    # reconnect, because a reconnect must never make a just-created VPS vanish.
    if not _vps_data_loaded_once:
        vps_data = get_vps_data()
        admin_data = {'admins': get_admins()}
        _vps_data_loaded_once = True
    total = sum(len(v) for v in vps_data.values())
    logger.info(f"Persistent state ready: {total} VPS records loaded.")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{BOT_NAME} VPS Manager"))
    logger.info(f"{BOT_NAME} Bot is ready!")
    # Reconcile application commands so stale Discord registrations (e.g. an old /manage) are removed.
    if not getattr(bot, '_application_commands_synced', False):
        try:
            synced = await asyncio.wait_for(bot.tree.sync(), timeout=45)
            bot._application_commands_synced = True
            logger.info('Application command sync complete: %d commands.', len(synced))
        except Exception as sync_exc:
            logger.warning('Application command sync failed; retrying on a later ready event: %s', sync_exc)
    global monitor_thread
    if monitor_thread is None or not monitor_thread.is_alive():
        monitor_thread = threading.Thread(target=resource_monitor, daemon=True, name="resource-monitor")
        monitor_thread.start()
    # Start auto-save background task (only once)
    if not hasattr(bot, '_auto_save_started'):
        bot._auto_save_started = True
        # Start background workers independently; a gateway reconnect should not
        # spawn duplicate monitors or launch every expensive job at the same instant.
        bot.loop.create_task(auto_save_task(), name='axionhost-auto-save')
        bot.loop.create_task(invite_startup_sync_task(), name='axionhost-invite-sync')
        bot.loop.create_task(rotating_presence_task(), name='axionhost-presence')
        bot.loop.create_task(resource_limit_watchdog_task(), name='axionhost-resource-watchdog')
        if not hasattr(bot, '_vox_ai_agent_started'):
            bot._vox_ai_agent_started = True
            bot.loop.create_task(vox_ai_agent_task())

@bot.event
async def on_close():
    """Stop background work and persist pending state before Discord closes."""
    global resource_monitor_active, _auto_save_pending
    resource_monitor_active = False
    try:
        if _auto_save_pending:
            save_vps_data()
            _auto_save_pending = False
    except Exception as exc:
        logger.error(f"Error saving state during shutdown: {exc}")
    logger.info("Shutdown cleanup completed.")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    """Handle stale/unknown slash commands cleanly and trigger one re-sync."""
    if isinstance(error, discord.app_commands.errors.CommandNotFound):
        logger.warning('Ignoring stale application command interaction: %s', getattr(error, 'name', 'unknown'))
        try:
            if not getattr(bot, '_application_commands_sync_retry', False):
                bot._application_commands_sync_retry = True
                async def _retry_sync():
                    try:
                        await asyncio.sleep(2)
                        synced = await bot.tree.sync()
                        bot._application_commands_synced = True
                        logger.info('Application command re-sync complete: %d commands.', len(synced))
                    except Exception as exc:
                        logger.warning('Application command re-sync failed: %s', exc)
                    finally:
                        bot._application_commands_sync_retry = False
                asyncio.create_task(_retry_sync(), name='axionhost-app-command-resync')
        except Exception:
            logger.debug('Could not schedule application command resync.', exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message('This command is outdated. Please try again in a few seconds.', ephemeral=True)
        except Exception:
            pass
        return
    logger.error('Application command error: %s', error, exc_info=True)
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message('An internal command error occurred. Please try again.', ephemeral=True)
    except Exception:
        pass

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=create_error_embed("Missing Argument", f"Please check command usage with `{PREFIX}help`."))
    elif isinstance(error, commands.BadArgument):
        usage = f"Use `{PREFIX}help` for command usage."
        if getattr(ctx, 'command', None) and ctx.command.name in ('cloudflare-fix', 'cloudflare-status', 'vps-diagnostics'):
            usage = f"Use `{PREFIX}{ctx.command.name} <VPS ID or container-name>` — e.g. `{PREFIX}{ctx.command.name} wbkajsydv-vps-1`"
        await ctx.send(embed=create_error_embed("Invalid Argument", usage))
    elif isinstance(error, AXIONHOSTMaintenanceError):
        await ctx.send(embed=create_warning_embed(
            "🔶 Under Maintenance",
            "🛠️ **Service maintenance is currently active.**\n\nOnly administrators can use bot commands while maintenance mode is ON.\nPlease try again when maintenance is finished."
        ))
    elif isinstance(error, commands.CheckFailure):
        error_msg = str(error) if str(error) else "You need admin permissions for this command. Contact support."
        await ctx.send(embed=create_error_embed("Access Denied", error_msg))
    elif isinstance(error, commands.CommandOnCooldown):
        retry = max(1, int(error.retry_after) + 0.999)
        await ctx.send(embed=create_error_embed("Slow Down", f"Please wait **{retry}s** before using this command again."))
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send(embed=create_error_embed("Server Only", "This command can only be used inside a Discord server."))
    elif isinstance(error, discord.Forbidden):
        await ctx.send(embed=create_error_embed("Permission Error", "Discord denied this action. Check the bot's channel/role permissions."))
    elif isinstance(error, discord.NotFound):
        await ctx.send(embed=create_error_embed("Error", "The requested resource was not found. Please try again."))
    elif isinstance(error, discord.HTTPException):
        logger.warning("Discord HTTP error in %s: %s", getattr(ctx.command, "qualified_name", "unknown"), error)
        return
    else:
        logger.exception("Command error in %s", getattr(ctx.command, "qualified_name", "unknown"), exc_info=error)
        # Surface the actual safe exception text instead of hiding every runtime
        # failure behind a generic message; this makes deployment/OS debugging possible.
        detail = str(getattr(error, "original", error)).strip()
        if len(detail) > 1500:
            detail = detail[:1497] + "..."
        await ctx.send(embed=create_error_embed("System Error", detail or "An unexpected error occurred. Support has been notified."))

# Bot commands
@bot.command(name='ping')
async def ping(ctx):
    """Check bot latency"""
    latency = round(bot.latency * 1000)
    embed = create_success_embed(
        "🏓 Pong!",
        f"Bot is responding perfectly!"
    )
    add_field(embed, "Latency", f"`{latency}ms`", inline=True)
    add_field(embed, "Status", "✅ Online", inline=True)
    add_field(embed, "Bot", f"`{BOT_NAME} v{BOT_VERSION}`", inline=True)
    await ctx.send(embed=embed)

@bot.command(name='uptime')
async def uptime(ctx):
    up = get_uptime()
    embed = create_info_embed("Host Uptime", up)
    await ctx.send(embed=embed)

@bot.command(name='thresholds')
@is_admin()
async def thresholds(ctx):
    embed = create_info_embed("Resource Thresholds", f"**CPU:** {CPU_THRESHOLD}%\n**RAM:** {RAM_THRESHOLD}%")
    await ctx.send(embed=embed)

@bot.command(name='set-threshold')
@is_admin()
async def set_threshold(ctx, cpu: int, ram: int):
    global CPU_THRESHOLD, RAM_THRESHOLD
    if cpu < 0 or ram < 0:
        await ctx.send(embed=create_error_embed("Invalid Thresholds", "Thresholds must be non-negative."))
        return
    CPU_THRESHOLD = cpu
    RAM_THRESHOLD = ram
    set_setting('cpu_threshold', str(cpu))
    set_setting('ram_threshold', str(ram))
    embed = create_success_embed("Thresholds Updated", f"**CPU:** {cpu}%\n**RAM:** {ram}%")
    await ctx.send(embed=embed)

@bot.command(name='set-status')
@is_admin()
async def set_status(ctx, activity_type: str, *, name: str):
    types = {
        'playing': discord.ActivityType.playing,
        'watching': discord.ActivityType.watching,
        'listening': discord.ActivityType.listening,
        'streaming': discord.ActivityType.streaming,
    }
    if activity_type.lower() not in types:
        await ctx.send(embed=create_error_embed("Invalid Type", "Valid types: playing, watching, listening, streaming"))
        return
    await bot.change_presence(activity=discord.Activity(type=types[activity_type.lower()], name=name))
    embed = create_success_embed("Status Updated", f"Set to {activity_type}: {name}")
    await ctx.send(embed=embed)

@bot.command(name="myvps")
async def my_vps(ctx):
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])

    # ─── No VPS Case ───────────────────────────────────────────
    if not vps_list:
        embed = create_error_embed(
            "❌ No VPS Found",
            f"You don’t have any **{BOT_NAME} VPS** yet."
        )
        embed.add_field(
            name="🚀 Quick Actions",
            value=(
                f"• `{PREFIX}manage` – Manage VPS\n"
                f"• Contact an admin to request a VPS"
            ),
            inline=False
        )
        await ctx.send(embed=embed)
        return

    # ─── Embed ────────────────────────────────────────────────
    embed = create_info_embed(
        title="🖥️ My VPS Dashboard",
        description="Your personal VPS overview"
    )

    total_vps = len(vps_list)
    running = suspended = whitelisted = 0
    vps_cards = []

    # ─── VPS Processing ───────────────────────────────────────
    for i, vps in enumerate(vps_list, start=1):
        node = get_node(vps.get("node_id"))
        node_name = node["name"] if node else "Unknown"

        config = vps.get("config", "Custom")
        ram = vps.get("ram", "0GB")
        cpu = vps.get("cpu", "0")
        storage = vps.get("storage", "0GB")

        if vps.get("suspended"):
            status = "⛔ SUSPENDED"
            suspended += 1
        elif vps.get("status") == "running":
            status = "🟢 RUNNING"
            running += 1
        else:
            status = "🔴 STOPPED"

        if vps.get("whitelisted"):
            whitelisted += 1

        # Build VPS card
        card = (
            f"**{i}.** `{vps['container_name']}`\n"
            f"{status} • `{config}`\n"
            f"⚙️ `{ram}` RAM • `{cpu}` CPU • `{storage}` Disk\n"
            f"📍 Node: `{node_name}`"
        )
        
        # Add expiration info if set
        if vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            
            if days_remaining < 0:
                expiration_badge = "🔴 EXPIRED"
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                expiration_badge = "🟡 EXPIRING"
            else:
                expiration_badge = "🟢 ACTIVE"
            
            card += f"\n⏰ {expiration_badge} • Expires: `{expiration_dt.strftime('%Y-%m-%d')}`"
        
        vps_cards.append(card)

    # ─── Row 1 : Summary ──────────────────────────────────────
    embed.add_field(
        name="📊 Summary",
        value=(
            f"🖥️ `{total_vps}` VPS\n"
            f"🟢 `{running}` Running\n"
            f"⛔ `{suspended}` Suspended\n"
            f"✅ `{whitelisted}` Whitelisted"
        ),
        inline=True
    )

    embed.add_field(
        name="⚡ Quick Actions",
        value=(
            f"`{PREFIX}manage`\n"
            f"`{PREFIX}reinstall`\n"
            f"`{PREFIX}status`"
        ),
        inline=True
    )

    embed.add_field(
        name="🧭 Tip",
        value="Use **manage** to control your VPS",
        inline=True
    )

    # ─── VPS Cards (Full Width) ───────────────────────────────
    vps_text = "\n\n".join(vps_cards)
    for i in range(0, len(vps_text), 1024):
        embed.add_field(
            name="🖥️ Your VPS",
            value=vps_text[i:i + 1024],
            inline=False
        )

    embed.set_footer(text=f"AxionHost • VPS Control Panel")
    embed.timestamp = ctx.message.created_at

    await ctx.send(embed=embed)

@bot.command(name='lxc-list')
@is_admin()
async def lxc_list(ctx, node_id: int = 1):
    try:
        result = await execute_lxc("", "list", node_id=node_id)
        node = get_node(node_id)
        embed = create_info_embed(f"LXC Containers List on {node['name']}", result)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Error", str(e)))

class NodeSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, expiry_days: int = None, deploy_mode: bool = False):
        super().__init__(timeout=300)
        self.ram = ram
        self.cpu = cpu
        self.disk = disk
        self.user = user
        self.ctx = ctx
        self.expiry_days = expiry_days if expiry_days and expiry_days > 0 else DEFAULT_VPS_EXPIRATION_DAYS
        self.deploy_mode = bool(deploy_mode)
        self.selected_node_id = None
        nodes = get_nodes()
        options = []
        caller_is_admin = is_admin_user_id(str(getattr(ctx.author, 'id', '')))
        try:
            default_node_id = _preferred_deployment_node_id()
        except Exception:
            default_node_id = 0
        # The previous UI marked the default option as Discord's `default=True`.
        # On mobile this made the option look already selected, so tapping Local
        # again did not emit a new interaction and the user appeared stuck.
        # Keep the default as an internal choice, but require an actual Continue
        # click or a real selection interaction.
        if default_node_id > 0 and get_node(default_node_id):
            self.selected_node_id = int(default_node_id)
        nodes = sorted(nodes, key=lambda n: (0 if int(n.get('id') or 0) == int(default_node_id) else 1, int(n.get('id') or 0)))
        for n in nodes:
            current_count = get_current_vps_count(n['id'])
            available = max(0, int(n.get('total_vps') or 0) - current_count)
            if caller_is_admin or current_count < int(n.get('total_vps') or 0):
                node_type = "📍 Local" if n['is_local'] else "🌐 Remote"
                default_note = " • Default" if int(n.get('id') or 0) == int(default_node_id) else ""
                desc = f"{n['location']} - {'Admin: no slot cap' if caller_is_admin else f'Available: {available}'}{default_note}"
                options.append(discord.SelectOption(
                    label=f"{n['name']} {node_type}",
                    value=str(n['id']),
                    description=desc[:100],
                    default=False,
                ))
        if not options:
            self.add_item(discord.ui.Select(placeholder="No available nodes", disabled=True))
        else:
            self.select = discord.ui.Select(placeholder="Select a Node for the VPS", options=options)
            self.select.callback = self.select_node
            self.add_item(self.select)
            continue_button = discord.ui.Button(label="Continue with Selected Node", style=discord.ButtonStyle.primary, row=1)
            continue_button.callback = self.continue_node
            self.add_item(continue_button)

    async def _open_backend(self, interaction: discord.Interaction, node_id: int):
        if str(interaction.user.id) != str(self.ctx.author.id):
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the command author can select."), ephemeral=True)
            return
        node = get_node(node_id)
        if not node:
            await interaction.response.send_message(embed=create_error_embed("Node Unavailable", f"Node `{node_id}` is no longer configured. Refresh and try again."), ephemeral=True)
            return
        if REMOTE_NODE_ONLY and bool(node.get('is_local')):
            await interaction.response.send_message(
                embed=create_error_embed("Local Node Disabled", "Remote-only mode is enabled. Set `REMOTE_NODE_ONLY=false` to deploy VPSs on the local controller."),
                ephemeral=True
            )
            return
        self.selected_node_id = int(node_id)
        self.select.disabled = True
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            await interaction.response.defer()
            backend_view = BackendSelectView(
                self.ram, self.cpu, self.disk, self.user, self.ctx,
                int(node_id), self.expiry_days, deploy_mode=self.deploy_mode
            )
            await interaction.edit_original_response(
                embed=create_info_embed(
                    "🧩 Select Virtualization",
                    f"**Node:** {node['name']} (`{node_id}`)\n"
                    f"**RAM:** {self.ram}GB  •  **CPU:** {self.cpu} vCPU  •  **Disk:** {self.disk}GB\n\n"
                    "Choose **LXC** or **KVM**. CPU allocation is fixed from the create command."
                ),
                view=backend_view
            )
        except Exception as exc:
            self.select.disabled = False
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = False
            logger.exception("Node selector transition failed for node %s", node_id)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=create_error_embed("Node Selection Failed", safe_error_summary("Node selection", exc)), ephemeral=True)
                else:
                    await interaction.response.send_message(embed=create_error_embed("Node Selection Failed", safe_error_summary("Node selection", exc)), ephemeral=True)
            except Exception:
                pass

    async def select_node(self, interaction: discord.Interaction):
        try:
            node_id = int(self.select.values[0])
        except (IndexError, ValueError, TypeError):
            await interaction.response.send_message(embed=create_error_embed("Node Selection Failed", "Please select a valid node."), ephemeral=True)
            return
        self.selected_node_id = node_id
        await self._open_backend(interaction, node_id)

    async def continue_node(self, interaction: discord.Interaction):
        node_id = self.selected_node_id
        if not node_id:
            await interaction.response.send_message(embed=create_error_embed("Select a Node", "Choose a node from the dropdown first."), ephemeral=True)
            return
        await self._open_backend(interaction, int(node_id))

async def allocate_unique_kvm_name(username: str, node_id: int) -> tuple[str, int]:
    sanitized = sanitize_username_for_container(str(username).lower()[:30])
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM vps")
        next_id = int(cur.fetchone()[0] or 0) + 1
    finally:
        conn.close()
    for _ in range(100):
        name = f"{sanitized}-vm-{next_id}"
        conn = get_db()
        try:
            row = conn.execute('SELECT id FROM vps WHERE container_name = ?', (name,)).fetchone()
        finally:
            conn.close()
        if row:
            next_id += 1
            continue
        try:
            if (get_node(node_id) or {}).get('is_local') and shutil.which('virsh'):
                out = await _run_local_process(['virsh', 'dominfo', name], timeout=10, check=False)
                if out:
                    next_id += 1
                    continue
        except Exception:
            pass
        return name, next_id
    raise RuntimeError('Could not allocate a unique KVM VM name.')


class BackendSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, node_id: int, expiry_days: int = None, deploy_mode: bool = False, cpu_model: str = 'host-model'):
        super().__init__(timeout=300)
        self.ram, self.cpu, self.disk = ram, cpu, disk
        self.user, self.ctx, self.node_id = user, ctx, node_id
        self.expiry_days = expiry_days if expiry_days and expiry_days > 0 else DEFAULT_VPS_EXPIRATION_DAYS
        self.deploy_mode = deploy_mode
        self.cpu_model = cpu_model
        options = [discord.SelectOption(label="LXC / Non-KVM", value="lxc", description="Fast, lightweight container; host kernel")]
        # Keep KVM visible when it is enabled on a local node so the processor
        # selector is never mysteriously missing. If prerequisites are not ready,
        # selecting KVM produces an explicit diagnostic instead of hiding the UI.
        node = get_node(node_id) or {}
        caps = _kvm_local_capabilities() if node.get('is_local') else {'ready': False, 'enabled': False}
        if node.get('is_local') and caps.get('enabled', KVM_ENABLED):
            if caps.get('ready'):
                desc = "Dedicated guest kernel + hardware virtualization"
            else:
                missing = []
                if not caps.get('virsh'): missing.append('virsh')
                if not caps.get('virt_install'): missing.append('virt-install')
                if not caps.get('qemu_img'): missing.append('qemu-img')
                if not caps.get('kvm_device'): missing.append('/dev/kvm')
                desc = "KVM enabled; missing: " + ', '.join(missing[:2]) if missing else "KVM prerequisites need attention"
            options.append(discord.SelectOption(label="KVM Virtual Machine", value="kvm", description=desc[:100]))
        self.select = discord.ui.Select(placeholder="Select virtualization mode", options=options)
        self.select.callback = self._select_backend
        self.add_item(self.select)

    async def _select_backend(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.ctx.author.id):
            await interaction.response.send_message(
                embed=create_error_embed("Access Denied", "Only the command author can select."), ephemeral=True
            )
            return
        await interaction.response.defer()
        backend = self.select.values[0]
        self.select.disabled = True
        if backend == 'kvm':
            repair = await _ensure_kvm_host_ready(auto_install=True)
            caps = repair['caps']
            if not repair.get('ready'):
                missing = _kvm_host_missing(caps)
                detail = "KVM host repair was attempted automatically."
                if repair.get('actions'): detail += "\n\nActions: " + '; '.join(repair['actions'])
                if repair.get('error'): detail += "\n\n⚠️ " + repair['error']
                if missing: detail += "\n\nStill missing: " + ', '.join(missing)
                await interaction.edit_original_response(embed=create_error_embed("KVM Host Not Ready", detail + "\n\nIf `/dev/kvm` is missing, this is a parent-host/provider nested-virtualization issue, not a Python package issue."), view=None)
                return
            view = ProcessorFamilySelectView(
                self.ram, self.cpu, self.disk, self.user, self.ctx, self.node_id,
                self.expiry_days, deploy_mode=self.deploy_mode
            )
            await interaction.edit_original_response(
                embed=create_info_embed(
                    "🧠 Select Processor",
                    f"**RAM:** {self.ram}GB  •  **CPU:** {self.cpu} vCPU  •  **Disk:** {self.disk}GB\n\n"
                    "Choose a virtual CPU family. Models are read from this node's libvirt/QEMU capabilities."
                ),
                view=view
            )
            return
        view = OSSelectView(
            self.ram, self.cpu, self.disk, self.user, self.ctx, self.node_id, self.expiry_days,
            backend='lxc', deploy_mode=self.deploy_mode, cpu_model='host-shared'
        )
        await interaction.edit_original_response(
            embed=create_info_embed(
                "🖥️ Select Operating System",
                f"**{self.cpu} vCPU** • **LXC**\n\nChoose the operating system for your VPS."
            ),
            view=view
        )




class CustomProcessorModal(discord.ui.Modal, title="Custom KVM Processor"):
    model_input = discord.ui.TextInput(
        label="Exact QEMU/libvirt CPU model",
        placeholder="Example: EPYC-Rome-v4 or Skylake-Client",
        required=True, max_length=120
    )
    def __init__(self, parent_view):
        super().__init__(timeout=300)
        self.parent_view = parent_view
    async def on_submit(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.parent_view.ctx.author.id):
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the command author can select the processor."), ephemeral=True)
            return
        requested = str(self.model_input.value).strip()
        models = await get_kvm_cpu_models()
        canonical = {m.lower(): m for m in models}.get(requested.lower())
        if models and not canonical:
            examples = ', '.join(models[:12])
            await interaction.response.send_message(
                embed=create_error_embed("Unsupported Processor", f"`{requested}` is not reported by this node.\n\nAvailable examples: `{examples}`\n\nUse an exact model returned by `virsh cpu-models x86_64`."), ephemeral=True
            )
            return
        # If libvirt could not expose the model list, do not pretend the model is
        # valid or silently replace it. Pass the exact request to virt-install; the
        # KVM creation path will return the real libvirt error if it is unsupported.
        await interaction.response.defer()
        await self.parent_view.show_os(interaction, canonical or requested)


class ProcessorModelSelectView(discord.ui.View):
    def __init__(self, parent_view, family: str):
        super().__init__(timeout=300)
        self.parent_view, self.family = parent_view, family
        self.models = []
    async def build(self):
        all_models = await get_kvm_cpu_models()
        caps = await get_kvm_cpu_capabilities()
        host_vendor = str(caps.get('host_vendor') or '').lower()
        self.models = [m for m in all_models if classify_kvm_cpu_model(m) == self.family]
        # Do not present a foreign-vendor CPU family on a host that cannot
        # expose it. libvirt domain capabilities are the authoritative filter.
        if host_vendor in ('amd', 'intel'):
            vendor_filtered = []
            for m in self.models:
                info = caps.get('models', {}).get(m, {})
                vendor = str(info.get('vendor') or '').lower()
                if vendor and host_vendor not in vendor:
                    continue
                vendor_filtered.append(m)
            if vendor_filtered:
                self.models = vendor_filtered
        visible = self.models[:25]
        if not visible:
            return False
        self.select = discord.ui.Select(
            placeholder=f"Select {self.family.upper()} processor model",
            options=[discord.SelectOption(label=m[:100], value=m[:100], description="Supported by this node") for m in visible]
        )
        self.select.callback = self.select_model
        self.add_item(self.select)
        return True
    async def select_model(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.parent_view.ctx.author.id):
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the command author can select."), ephemeral=True)
            return
        model = self.select.values[0]
        self.select.disabled = True
        await interaction.response.defer()
        await self.parent_view.show_os(interaction, model)


class ProcessorFamilySelectView(discord.ui.View):
    def __init__(self, ram, cpu, disk, user, ctx, node_id, expiry_days=None, deploy_mode=False):
        super().__init__(timeout=300)
        self.ram, self.cpu, self.disk = ram, cpu, disk
        self.user, self.ctx, self.node_id = user, ctx, node_id
        self.expiry_days = expiry_days if expiry_days and expiry_days > 0 else DEFAULT_VPS_EXPIRATION_DAYS
        self.deploy_mode = deploy_mode
        self.message = None
        self.select = discord.ui.Select(
            placeholder="Select processor family",
            options=[
                discord.SelectOption(label="⚙️ Auto / Host Model", value="auto", description="Let libvirt choose a compatible model"),
                discord.SelectOption(label="🚀 AMD / Ryzen / EPYC", value="amd", description="AMD/Zen-family models reported by this node"),
                discord.SelectOption(label="🔷 Intel", value="intel", description="Intel/Xeon/Core models reported by this node"),
                discord.SelectOption(label="⚡ Host Passthrough", value="host-passthrough", description="Expose host CPU directly; migration is less portable"),
                discord.SelectOption(label="🛠️ Custom Processor", value="custom", description="Enter an exact supported QEMU/libvirt model")
            ]
        )
        self.select.callback = self.select_family
        self.add_item(self.select)
    async def show_os(self, interaction, cpu_model):
        view = OSSelectView(
            self.ram, self.cpu, self.disk, self.user, self.ctx, self.node_id, self.expiry_days,
            backend='kvm', deploy_mode=self.deploy_mode, cpu_model=cpu_model
        )
        embed = create_info_embed(
            "🖥️ Select Operating System",
            f"**{self.cpu} vCPU** • **KVM** • **Processor:** `{processor_display_name(cpu_model)}`\n\nChoose the operating system for your VPS."
        )
        if self.message is not None:
            await self.message.edit(embed=embed, view=view)
        else:
            await interaction.edit_original_response(embed=embed, view=view)
    async def select_family(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.ctx.author.id):
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the command author can select."), ephemeral=True)
            return
        family = self.select.values[0]
        self.select.disabled = True
        if family == 'custom':
            self.message = interaction.message
            await interaction.response.send_modal(CustomProcessorModal(self))
            return
        if family in ('auto', 'host-passthrough'):
            await self.show_os_after_defer(interaction, 'host-model' if family == 'auto' else 'host-passthrough')
            return
        view = ProcessorModelSelectView(self, family)
        if not await view.build():
            await interaction.response.edit_message(
                embed=create_error_embed("No Compatible Models", f"No {family.upper()} CPU models were reported by this node. Choose Auto/Host Model instead."),
                view=self
            )
            return
        await interaction.response.edit_message(
            embed=create_info_embed("🧠 Select Processor Model", f"**Family:** `{family.upper()}` • **{self.cpu} vCPU**\n\nSelect a model supported by this node."),
            view=view
        )
    async def show_os_after_defer(self, interaction, cpu_model):
        await interaction.response.defer()
        await self.show_os(interaction, cpu_model)

class OSSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, node_id: int, expiry_days: int = None, backend: str = 'lxc', deploy_mode: bool = False, cpu_model: str = 'host-model'):
        super().__init__(timeout=300)
        self.ram = ram
        self.cpu = cpu
        self.disk = disk
        self.user = user
        self.ctx = ctx
        self.node_id = node_id
        self.backend = backend
        self.deploy_mode = deploy_mode
        self.cpu_model = cpu_model
        self.expiry_days = expiry_days if expiry_days and expiry_days > 0 else DEFAULT_VPS_EXPIRATION_DAYS
        os_source = [o for o in OS_OPTIONS if (self.backend != 'kvm' or o['value'] in KVM_SUPPORTED_IMAGES)]
        self.select = discord.ui.Select(
            placeholder="Select an OS for the VPS",
            options=[discord.SelectOption(label=o["label"], value=o["value"]) for o in os_source]
        )
        self.select.callback = self.select_os
        self.add_item(self.select)

    async def select_os(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.ctx.author.id):
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the command author can select."), ephemeral=True)
            return
        if self.deploy_mode and not is_admin_user_id(str(interaction.user.id)):
            if not is_free_deploy_enabled():
                await interaction.response.send_message(embed=create_error_embed("Free Deploy Disabled", "An administrator disabled free deployment before this VPS was created."), ephemeral=True)
                _deploying_users.discard(str(self.user.id))
                return
            owned = sum(len(items) for uid, items in vps_data.items() if str(uid) == str(self.user.id))
            total, *_ = get_slot_stats_deploy()
            free_cfg = get_free_deploy_config()
            if (free_cfg['user_limit'] > 0 and owned >= free_cfg['user_limit']) or (DEPLOY_SLOT > 0 and total >= DEPLOY_SLOT):
                await interaction.response.send_message(embed=create_error_embed("Free Deploy Limit Reached", "Your per-user limit or the global free VPS capacity has been reached."), ephemeral=True)
                _deploying_users.discard(str(self.user.id))
                return
        os_version = self.select.values[0]
        self.select.disabled = True
        # Count limits are bypassed for admins, but physical host protection is
        # never bypassed. This prevents an "unlimited admin" from exhausting
        # RAM/CPU/disk and causing LXD pthread/process failures.
        try:
            capacity_ok, capacity_reason = await check_node_capacity_for_vps(self.node_id, self.ram, self.cpu, self.disk)
        except Exception as cap_exc:
            capacity_ok, capacity_reason = False, safe_error_summary('Host capacity check', cap_exc)
        if not capacity_ok:
            self.select.disabled = False
            _deploying_users.discard(str(self.user.id))
            await interaction.response.send_message(
                embed=create_error_embed('Node Capacity Protection', capacity_reason + '\n\nAdmin VPS count is unlimited, but deployment is blocked when the node cannot safely provide the requested resources.'),
                ephemeral=True
            )
            return
        creating_embed = create_info_embed("Creating VPS", f"Deploying {os_version} VPS for {self.user.mention} on node {self.node_id}...")
        await interaction.response.edit_message(embed=creating_embed, view=self)
        user_id = str(self.user.id)
        # Allocate a name that is unique in BOTH the database and the real LXC node.
        # This fixes stale-container collisions such as `rehan404-vps-1 already exists`.
        container_name = None
        global_vps_id = None
        created = False
        ram_mb = self.ram * 1024
        try:
            if self.backend == 'kvm':
                container_name, global_vps_id = await allocate_unique_kvm_name(self.user.name, self.node_id)
                if os_version not in KVM_SUPPORTED_IMAGES:
                    raise RuntimeError(f"KVM does not support `{os_version}` on this build.")
                root_password = generate_strong_password()
                kvm_info = await create_kvm_instance(container_name, os_version, self.node_id, self.ram, self.cpu, self.disk, root_password, self.cpu_model)
                created = True
                await asyncio.sleep(1)
                try:
                    kvm_networks = await wait_for_kvm_network(container_name, timeout=10)
                except Exception as net_exc:
                    logger.warning('Initial KVM network discovery failed for %s: %s', container_name, net_exc)
                    kvm_networks = {}
                kvm_info['networks'] = kvm_networks
                if not kvm_networks:
                    kvm_info['network_diagnostic'] = {'status': 'pending', 'message': 'Guest network is still converging; the VPS is not rolled back.'}
                # Cloud-init normally enables password SSH, but images can ship
                # with restrictive sshd defaults. Verify the effective config now
                # so a newly created VPS never advertises a broken SSH login.
                kvm_ssh = await configure_kvm_guest_ssh(container_name, root_password)
                ssh_pending = False
                ssh_error = ''
                if not kvm_ssh.get('ok'):
                    # QGA/cloud-init can still be starting. Do not rollback a
                    # valid KVM VM just because guest SSH is not ready yet.
                    await asyncio.sleep(5)
                    kvm_ssh = await configure_kvm_guest_ssh(container_name, root_password)
                if not kvm_ssh.get('ok'):
                    ssh_pending = True
                    ssh_error = str(kvm_ssh.get('error') or kvm_ssh.get('raw') or '')[-1600:]
                    logger.warning('KVM SSH setup pending for %s: %s', container_name, ssh_error)
                status = 'running'
                config_extra = f"KVM CPU model: {kvm_info.get('cpu_model', self.cpu_model)}"
                if kvm_info.get('cpu_fallback'):
                    config_extra += f"\n⚠️ {kvm_info['cpu_fallback']}"
                if ssh_pending:
                    kvm_info['ssh_pending'] = True
                    kvm_info['ssh_error'] = ssh_error
                    config_extra += "\n⏳ SSH setup is still initializing; the VPS itself is running."
            else:
                container_name, global_vps_id = await allocate_unique_container_name(self.user.name, self.node_id)
                await create_instance_from_image(container_name, os_version, self.node_id)
                created = True
                await execute_lxc(container_name, f"config set {container_name} limits.memory {ram_mb}MB", node_id=self.node_id)
                await execute_lxc(container_name, f"config set {container_name} limits.cpu {self.cpu}", node_id=self.node_id)
                await execute_lxc(container_name, f"config device set {container_name} root size={self.disk}GB", node_id=self.node_id)
                await apply_lxc_config(container_name, self.node_id)
                await execute_lxc(container_name, f"start {container_name}", node_id=self.node_id)
                await apply_internal_permissions(container_name, self.node_id)
                await recreate_port_forwards(container_name)
                root_password = generate_strong_password()
                success, result = await configure_ssh(container_name, self.node_id, root_password)
                if not success:
                    logger.warning(f"SSH configuration partially failed: {result}")
                if HOST_MOTD:
                    try:
                        await execute_lxc(container_name, f"exec {container_name} -- sh -c {shlex.quote(HOST_MOTD)}", node_id=self.node_id)
                    except Exception as e:
                        logger.warning(f"HOST_MOTD execution failed for {container_name}: {e}")
                status = 'running'
                config_extra = f"LXC security: privileged={VPS_PRIVILEGED}, nesting={VPS_DOCKER_READY or VPS_NESTING}, Docker-ready={VPS_DOCKER_READY}"

            config_str = f"{self.ram}GB RAM / {self.cpu} CPU / {self.disk}GB Disk"
            vps_info = {
                "container_name": container_name,
                "node_id": self.node_id,
                "ram": f"{self.ram}GB",
                "cpu": str(self.cpu),
                "storage": f"{self.disk}GB",
                "config": config_str,
                "os_version": os_version,
                "status": "running",
                "suspended": False,
                "whitelisted": False,
                "suspension_history": [],
                "created_at": datetime.now().isoformat(),
                "shared_with": [],
                "expiration_date": (datetime.now() + timedelta(days=self.expiry_days)).isoformat(),
                "root_password": root_password,
                "networks": kvm_info.get("networks", {}) if self.backend == "kvm" else {},
                "id": global_vps_id,
                "backend": self.backend,
                "cpu_model": kvm_info.get("cpu_model", "libvirt-default") if self.backend == "kvm" else None
            }
            if user_id not in vps_data:
                vps_data[user_id] = []
            vps_data[user_id].append(vps_info)
            save_vps_data_immediate()
            if not verify_vps_persisted(vps_info):
                raise RuntimeError(f"VPS {container_name} was created but could not be persisted to SQLite.")

            # Provision a fresh Pinggy TCP endpoint for every newly deployed VPS.
            # Pinggy assigns the public hostname/port; requesting remote port 0
            # asks Pinggy to allocate a random available public TCP port.
            # The VPS login itself always uses username root and this VPS's
            # cryptographically generated root_password.
            try:
                if self.backend == 'kvm':
                    pinggy_host, pinggy_port = await asyncio.wait_for(
                        kvm_guest_pinggy_tunnel(container_name, timeout=60), timeout=75
                    )
                    pinggy_url = f"tcp://{pinggy_host}:{pinggy_port}"
                else:
                    pinggy_info = await asyncio.wait_for(
                        start_pinggy_session(container_name, self.node_id), timeout=150
                    )
                    pinggy_host = (pinggy_info or {}).get('host')
                    pinggy_port = (pinggy_info or {}).get('port')
                    pinggy_url = (pinggy_info or {}).get('url')
                if pinggy_host and pinggy_port:
                    vps_info.update({
                        'pinggy_host': str(pinggy_host),
                        'pinggy_port': str(pinggy_port),
                        'pinggy_url': str(pinggy_url or f"tcp://{pinggy_host}:{pinggy_port}"),
                        'pinggy_started_at': datetime.now().isoformat(),
                        'pinggy_status': 'connected',
                        'ssh_username': 'root',
                    })
                    save_vps_data_immediate()
                    logger.info('Fresh Pinggy endpoint assigned to %s: %s:%s', container_name, pinggy_host, pinggy_port)
                else:
                    vps_info['pinggy_status'] = 'failed'
                    vps_info['pinggy_error'] = 'Pinggy did not publish a TCP endpoint.'
                    save_vps_data_immediate()
                    logger.warning('Pinggy did not return endpoint for newly deployed VPS %s', container_name)
            except Exception as pinggy_exc:
                vps_info['pinggy_status'] = 'failed'
                vps_info['pinggy_error'] = str(pinggy_exc)[:1200]
                save_vps_data_immediate()
                logger.warning('Pinggy setup failed for newly deployed VPS %s: %s', container_name, pinggy_exc, exc_info=True)

            # If QGA/SSH was not ready yet, keep the VPS alive and retry repair
            # in the background instead of failing the whole deployment.
            if self.backend == 'kvm' and kvm_info.get('ssh_pending'):
                vps_info['kvm_ssh_pending'] = True
                vps_info['kvm_ssh_error'] = kvm_info.get('ssh_error', '')
                save_vps_data_immediate()

                async def _post_provision_kvm_ssh():
                    last = kvm_info.get('ssh_error', '')
                    for attempt in range(1, 9):
                        try:
                            await asyncio.sleep(min(10 * attempt, 45))
                            state = await configure_kvm_guest_ssh(container_name, root_password)
                            if state.get('ok'):
                                vps_info['kvm_ssh_pending'] = False
                                vps_info['kvm_ssh_ready_at'] = datetime.now().isoformat()
                                vps_info['kvm_ssh_error'] = None
                                save_vps_data_immediate()
                                logger.info('KVM SSH became ready for %s on retry %d', container_name, attempt)
                                return
                            last = str(state.get('error') or state.get('raw') or '')[-1600:]
                        except Exception as exc:
                            last = str(exc)[-1600:]
                    vps_info['kvm_ssh_pending'] = True
                    vps_info['kvm_ssh_error'] = last
                    save_vps_data_immediate()
                    logger.warning('KVM SSH remains pending for %s after retries: %s', container_name, last)

                asyncio.create_task(_post_provision_kvm_ssh(), name=f"kvm-ssh-bootstrap-{container_name}")

            # Cloudflare client/tunnel setup is a post-provisioning task. It must
            # never roll back an otherwise healthy VPS. The installer is still
            # run automatically for LXC guests when enabled; failures are stored
            # in the VPS record and reported to the owner/admin. A tunnel token
            # is optional for client-only installation.
            cloudflare_result = None
            if self.backend == 'lxc' and CLOUDFLARE_INSTALL_ENABLED:
                # Do not hold the Discord creation interaction open for up to 5
                # minutes while cloudflared downloads/restarts. Persist the VPS
                # first, return success, then perform the optional install in a
                # background task. A failed Cloudflare setup can never make VPS
                # creation appear stuck or roll back a healthy VPS.
                vps_info['cloudflare'] = {
                    'enabled': True, 'installed': False, 'tunnel_active': False,
                    'pending': True, 'checked_at': datetime.now().isoformat()
                }
                save_vps_data_immediate()

                async def _post_provision_cloudflare():
                    try:
                        result = await asyncio.wait_for(
                            _safe_cloudflare_install(container_name, self.node_id), timeout=300
                        )
                        current = vps_info
                        current['cloudflare'] = {
                            'enabled': True,
                            'installed': 'CLOUDFLARED_INSTALLED=YES' in (result or '') or 'CLOUDFLARED_SERVICE=ACTIVE' in (result or ''),
                            'tunnel_active': 'CLOUDFLARED_SERVICE=ACTIVE' in (result or ''),
                            'pending': False,
                            'checked_at': datetime.now().isoformat(),
                            'details': (result or '')[-1200:]
                        }
                        save_vps_data_immediate()
                    except Exception as cf_exc:
                        logger.warning("Cloudflare background setup failed for %s: %s", container_name, cf_exc)
                        vps_info['cloudflare'] = {
                            'enabled': True, 'installed': False, 'tunnel_active': False,
                            'pending': False, 'checked_at': datetime.now().isoformat(),
                            'error': str(cf_exc)[:1000]
                        }
                        save_vps_data_immediate()

                asyncio.create_task(_post_provision_cloudflare(), name=f'cloudflare-setup-{container_name}')

            if self.ctx.guild:
                vps_role = await get_or_create_vps_role(self.ctx.guild)
                if vps_role:
                    try:
                        await self.user.add_roles(vps_role, reason=f"{BOT_NAME} VPS ownership granted")
                    except discord.Forbidden:
                        logger.warning(f"Failed to assign VPS role to {self.user.name}")
            success_embed = create_success_embed("VPS Created Successfully")
            add_field(success_embed, "Owner", self.user.mention, True)
            add_field(success_embed, "VPS ID", f"#{global_vps_id}", True)
            add_field(success_embed, "Container", f"`{container_name}`", True)
            add_field(success_embed, "Node", get_node(self.node_id)['name'], True)
            add_field(success_embed, "Resources", f"**RAM:** {self.ram}GB\n**CPU:** {self.cpu} Cores\n**Storage:** {self.disk}GB", False)
            add_field(success_embed, "OS", os_version, True)
            add_field(success_embed, "SSH Configuration", "✅ Configured (PasswordAuth enabled)", True)
            add_field(success_embed, "SSH & Password", "✅ SSH configured for password authentication\n🔐 Root password generated and sent via DM\n📧 Check your DMs for SSH credentials!", False)
            if self.backend == 'lxc' and CLOUDFLARE_INSTALL_ENABLED:
                cf = vps_info.get('cloudflare') or {}
                if cf.get('pending'):
                    cf_text = "⏳ cloudflared setup is running in the background; VPS creation is already complete."
                elif cf.get('tunnel_active'):
                    cf_text = "✅ cloudflared installed and tunnel service is active."
                elif cf.get('installed'):
                    cf_text = "✅ cloudflared client installed. Tunnel token/service is not active or not configured."
                else:
                    cf_text = "⚠️ cloudflared setup needs attention. VPS creation was completed safely; use cloudflare-fix/status."
                add_field(success_embed, "☁️ Cloudflare", cf_text, False)
            add_field(success_embed, "Virtualization", f"**Backend:** `{self.backend.upper()}`\n**Processor:** `{self.cpu} vCPU`\n{config_extra}", False)
            add_field(success_embed, "Disk Note", "Run `sudo resize2fs /` inside VPS if needed to expand filesystem.", False)
            await interaction.followup.send(embed=success_embed)
            dm_embed = create_success_embed("🎉 VPS Created Successfully!", f"Your new VPS is ready to use!")
            
            # VPS Details Section
            vps_details = f"""
**VPS ID:** #{global_vps_id}
**Container:** `{container_name}`
**Configuration:** {config_str}
**Operating System:** {os_version}
**Status:** 🟢 Running
**Created:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Expiration:** {(datetime.now() + timedelta(days=self.expiry_days)).strftime('%Y-%m-%d %H:%M:%S')} ({self.expiry_days} days)
"""
            add_field(dm_embed, "📊 VPS Details", vps_details.strip(), False)
            
            # Get all network interfaces - with timeout to prevent hanging
            try:
                networks = await asyncio.wait_for(get_kvm_networks(container_name), timeout=5.0) if self.backend == 'kvm' else await asyncio.wait_for(
                    get_container_networks(container_name, self.node_id),
                    timeout=3.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout getting networks for {container_name}")
                networks = {}
            
            if networks:
                # Format SSH access info with all real interfaces
                ssh_access_info = "**🖥️ Available Connection Points:**\n"
                for interface, ip in sorted(networks.items()):
                    ssh_access_info += f"└─ **{interface}:** `ssh root@{ip}`\n"
                ssh_access_info += f"\n**🔑 Login Credentials:**\n"
                ssh_access_info += f"**Username:** `root`\n"
                ssh_access_info += f"**Password:** `{root_password}`\n"
                ssh_access_info += f"\n**⚠️ Important:** Save this password securely!"
            else:
                # If no interfaces found, still show credentials (important!)
                ssh_access_info = "**🔑 Login Credentials:**\n"
                ssh_access_info += f"**Username:** `root`\n"
                ssh_access_info += f"**Password:** `{root_password}`\n"
                ssh_access_info += f"\n**📡 Network Setup:**\n"
                ssh_access_info += "Your VPS is initializing its network interfaces.\n"
                ssh_access_info += "They will be available in a few seconds.\n"
                ssh_access_info += f"\n**⚠️ Important:** Save this password securely!"
            
            add_field(dm_embed, "🔐 SSH Credentials & Access", ssh_access_info, False)
            pinggy_host = vps_info.get('pinggy_host')
            pinggy_port = vps_info.get('pinggy_port')
            if pinggy_host and pinggy_port:
                pinggy_ips = await asyncio.to_thread(resolve_pinggy_ipv4, pinggy_host)
                vps_info['pinggy_ips'] = pinggy_ips
                pinggy_ip_text = ', '.join(pinggy_ips[:5]) if pinggy_ips else 'DNS lookup unavailable'
                pinggy_access = (
                    f"**Termius / SSH Command:**\n`ssh root@{pinggy_host} -p {pinggy_port}`\n\n"
                    f"**Host:** `{pinggy_host}`\n"
                    f"**Port:** `{pinggy_port}`\n"
                    f"**Pinggy Public IP:** `{pinggy_ip_text}`\n"
                    f"**Username:** `root`\n"
                    f"**Password:** `{root_password}`\n\n"
                    "Pinggy IPs are shared provider ingress addresses, not dedicated VPS IPs. The endpoint may change after reconnecting the tunnel."
                )
                add_field(dm_embed, "🌐 Pinggy SSH Tunnel", pinggy_access, False)
            else:
                add_field(
                    dm_embed, "🌐 Pinggy SSH Tunnel",
                    "⚠️ Pinggy could not publish an endpoint during deployment. Use **Reconnect Tunnel** in VPS management; the root username/password above remain valid.",
                    False
                )
            
            # SSH Features
            features_info = """✅ **SSH:** Password authentication enabled
✅ **SFTP:** File transfer available
✅ **Root:** Full root access granted
✅ **Ports:** All ports available for forwarding
✅ **Virtualization:** Backend-specific isolation
✅ **Features:** Complete Linux container with full capabilities"""
            add_field(dm_embed, "⚙️ Features & Capabilities", features_info, False)
            
            # Support Section
            support_info = f"""**Need Help?**
• Use `{PREFIX}manage` to start/stop/reinstall your VPS
• Click 🔐 in manage to regenerate password
• Contact admin for issues or upgrades
• Check logs with: `journalctl -xe`"""
            add_field(dm_embed, "📞 Support & Management", support_info, False)
            try:
                await self.user.send(embed=dm_embed)
            except discord.Forbidden:
                await self.ctx.send(embed=create_info_embed("Notification Failed", f"Couldn't send DM to {self.user.mention}. Please ensure DMs are enabled."))
            if self.deploy_mode:
                _deploying_users.discard(str(self.user.id))
        except Exception as e:
            logger.exception("Admin VPS creation failed for %s", self.user)
            if created and container_name:
                try:
                    if self.backend == 'kvm':
                        await execute_kvm(container_name, f"delete {container_name}", self.node_id)
                    else:
                        await safe_delete_instance(container_name, self.node_id)
                    logger.info("Cleaned up partial VPS %s", container_name)
                except Exception as cleanup_error:
                    logger.error("Failed to clean up partial VPS %s: %s", container_name, cleanup_error)
            error_embed = create_error_embed("Creation Failed", f"Error: {str(e)}")
            await interaction.followup.send(embed=error_embed)
            if self.deploy_mode:
                _deploying_users.discard(str(self.user.id))

def _ai_vps_records():
    """Yield live in-memory VPS records without exposing credentials."""
    records = []
    for owner_id, items in vps_data.items():
        for vps in items:
            if isinstance(vps, dict) and vps.get('container_name'):
                records.append((str(owner_id), vps))
    return records


async def _ai_lxc_ssh_health(container_name: str, node_id: int) -> Dict[str, Any]:
    cmd = r'''set +e
printf 'SSH_CONFIG='
sshd -t >/dev/null 2>&1 && echo OK || echo FAIL
printf 'PASSWORD_AUTH='
sshd -T 2>/dev/null | grep -Eq '^passwordauthentication yes$' && echo YES || echo NO
printf 'ROOT_LOGIN='
sshd -T 2>/dev/null | grep -Eq '^permitrootlogin yes$' && echo YES || echo NO
printf 'PORT22='
(ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null || true) | grep -Eq '(^|[[:space:]])[^ ]*:22[[:space:]]' && echo LISTENING || echo CLOSED
'''
    try:
        raw = await execute_lxc(container_name, f"exec {container_name} -- sh -c {shlex.quote(cmd)}", node_id=node_id, timeout=20)
        data = {}
        for line in str(raw).splitlines():
            if '=' in line:
                k,v=line.split('=',1); data[k.lower()] = v.strip()
        data['ok'] = data.get('ssh_config') == 'OK' and data.get('password_auth') == 'YES' and data.get('root_login') == 'YES' and data.get('port22') == 'LISTENING'
        return data
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


async def _ai_kvm_ssh_health(vm_name: str) -> Dict[str, Any]:
    cmd = r'''set +e
printf 'SSH_CONFIG='
sshd -t >/dev/null 2>&1 && echo OK || echo FAIL
E="$(sshd -T -C user=root,addr=127.0.0.1,host=localhost 2>/dev/null || sshd -T 2>/dev/null || true)"
printf '%s\n' "$E" | grep -Eq '^passwordauthentication yes$' && echo 'PASSWORD_AUTH=YES' || echo 'PASSWORD_AUTH=NO'
printf '%s\n' "$E" | grep -Eq '^permitrootlogin yes$' && echo 'ROOT_LOGIN=YES' || echo 'ROOT_LOGIN=NO'
printf 'PORT22='
(ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null || true) | grep -Eq '(^|[[:space:]])[^ ]*:22[[:space:]]' && echo LISTENING || echo CLOSED
'''
    try:
        raw=await kvm_guest_exec(vm_name,cmd,timeout=20)
        data={}
        for line in str(raw).splitlines():
            if '=' in line:
                k,v=line.split('=',1); data[k.lower()] = v.strip()
        data['ok']=data.get('ssh_config')=='OK' and data.get('password_auth')=='YES' and data.get('root_login')=='YES' and data.get('port22')=='LISTENING'
        return data
    except Exception as exc:
        return {'ok':False,'error':str(exc)}


async def _ai_tunnel_alive(vps: Dict[str, Any]) -> bool:
    cn = str(vps.get('container_name'))
    backend = str(vps.get('backend','lxc')).lower()
    try:
        if backend == 'kvm':
            raw = await kvm_guest_exec(cn, 'if [ -f /tmp/pinggy-kvm.pid ] && kill -0 "$(cat /tmp/pinggy-kvm.pid)" 2>/dev/null; then cat /tmp/pinggy-kvm.log 2>/dev/null; fi', timeout=10)
        else:
            raw = await execute_lxc(cn, f"exec {cn} -- sh -c 'if [ -f /tmp/pinggy.pid ] && kill -0 \"$(cat /tmp/pinggy.pid)\" 2>/dev/null; then cat /tmp/pinggy.log 2>/dev/null; fi'", node_id=vps.get('node_id'), timeout=10)
        m=re.search(r'tcp://([^\s:]+):(\d+)', str(raw or ''))
        if m:
            vps['pinggy_host'], vps['pinggy_port'] = m.group(1), m.group(2)
            vps['pinggy_provider'] = 'pinggy-kvm' if backend == 'kvm' else 'pinggy-lxc'
            return True
    except Exception:
        pass
    return False


async def _ai_lxc_state(container_name: str, node_id: int) -> Dict[str, Any]:
    """Return exact LXC state without throwing for a missing/stopped instance."""
    try:
        raw = await execute_lxc('', f'list {shlex.quote(container_name)} --format=json', node_id=node_id, timeout=20)
        items = json.loads(raw) if raw else []
        if isinstance(items, list) and items:
            item = items[0]
            return {'exists': True, 'status': str(item.get('status') or '').lower(), 'project': item.get('project')}
        # Some LXD versions return an object for an exact-name list.
        if isinstance(items, dict) and items.get('name'):
            return {'exists': True, 'status': str(items.get('status') or '').lower(), 'project': items.get('project')}
    except Exception as exc:
        msg = str(exc).lower()
        if any(x in msg for x in ('not found', 'does not exist', 'no such instance')):
            return {'exists': False, 'status': 'missing'}
        logger.debug('[VoxAI] LXC state check failed for %s: %s', container_name, exc)
    return {'exists': False, 'status': 'unknown'}

async def _ai_mark_orphaned(vps: Dict[str, Any], detail: str) -> None:
    """Stop retry storms for DB records whose real LXC instance no longer exists."""
    vps['status'] = 'orphaned'
    vps['ssh_ready'] = False
    vps['ai_last_error'] = str(detail)[-500:]
    try:
        with DB_LOCK:
            conn = get_db()
            try:
                conn.execute('UPDATE vps SET status=? WHERE container_name=?', ('orphaned', str(vps.get('container_name'))))
                conn.commit()
            finally:
                conn.close()
    except Exception:
        logger.exception('[VoxAI] Could not persist orphaned state for %s', vps.get('container_name'))

async def _ai_connection_doctor(vps: Dict[str, Any]) -> Dict[str, Any]:
    """Deep read-mostly connection diagnosis for SSH, DNS, routing and tunnels."""
    cn = str(vps.get('container_name') or '')
    backend = str(vps.get('backend', 'lxc')).lower()
    node_id = int(vps.get('node_id') or 1)
    if not cn:
        return {'ok': False, 'category': 'invalid', 'issues': ['Missing VPS container name.']}
    script = r"""set +e
printf 'INIT=%s\n' "$(cat /proc/1/comm 2>/dev/null || true)"
printf 'HOSTNAME=%s\n' "$(hostname 2>/dev/null || true)"
printf 'IPV4=%s\n' "$(hostname -I 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]+\./){print $i; exit}}')"
printf 'SSH_SERVICE='; (systemctl is-active ssh 2>/dev/null || systemctl is-active sshd 2>/dev/null || true); printf '\n'
printf 'SSH_CONFIG='; sshd -t >/dev/null 2>&1 && echo OK || echo FAIL
printf 'SSH_PORT22='; (ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null || true) | grep -Eq '(^|[[:space:]])[^ ]*:22[[:space:]]' && echo LISTENING || echo CLOSED
printf 'ROOT_LOGIN='; sshd -T 2>/dev/null | grep -Eq '^permitrootlogin yes$' && echo YES || echo NO
printf 'PASSWORD_AUTH='; sshd -T 2>/dev/null | grep -Eq '^passwordauthentication yes$' && echo YES || echo NO
printf 'DNS='; getent hosts free.pinggy.io >/dev/null 2>&1 && echo OK || echo FAIL
printf 'DNS_GOOGLE='; getent hosts google.com >/dev/null 2>&1 && echo OK || echo FAIL
printf 'ROUTE='; ip route get 1.1.1.1 2>/dev/null | head -n1
printf 'PING_IP='; ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 && echo OK || echo FAIL
printf 'HTTPS='; curl -4 -fsS --connect-timeout 5 --max-time 10 https://www.google.com/generate_204 >/dev/null 2>&1 && echo OK || echo FAIL
printf 'PINGGY_TCP='; if (command -v nc >/dev/null 2>&1 && nc -4 -z -w5 free.pinggy.io 443 >/dev/null 2>&1) || (timeout 7 bash -c '</dev/tcp/free.pinggy.io/443' >/dev/null 2>&1); then echo OK; else echo FAIL; fi
printf 'SSHX='; command -v sshx >/dev/null 2>&1 && echo INSTALLED || echo MISSING
printf 'PINGGY_SUP='; p=$(cat /var/lib/rgnodes/pinggy.supervisor.pid 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo RUNNING || echo STOPPED
printf 'PINGGY_ENDPOINT='; cat /var/lib/rgnodes/pinggy.info 2>/dev/null | tail -n1
printf 'PINGGY_LOG='; tail -n 8 /var/lib/rgnodes/pinggy.log 2>/dev/null | tr '\n' ' ' | cut -c1-900
printf '\nPIDS_CURRENT='; cat /sys/fs/cgroup/pids.current 2>/dev/null || true
printf 'PIDS_MAX='; cat /sys/fs/cgroup/pids.max 2>/dev/null || true
printf 'THREADS='; ps -eLf 2>/dev/null | wc -l
printf 'LOAD='; cat /proc/loadavg 2>/dev/null
"""
    try:
        raw = await (kvm_guest_exec(cn, script, timeout=30) if backend == 'kvm' else _exec_guest_bash(cn, node_id, script, timeout=30))
    except Exception as exc:
        return {'ok': False, 'category': 'guest_exec', 'issues': [str(exc)[-1200:]], 'raw': str(exc)[-3000:]}
    data = {}
    for line in str(raw or '').splitlines():
        if '=' in line:
            k,v=line.split('=',1); data[k.strip().lower()] = v.strip()
    issues=[]
    def isval(key, *vals): return str(data.get(key,'')).strip().upper() in {str(x).upper() for x in vals}
    if isval('ssh_config','FAIL'): issues.append('SSH configuration is invalid.')
    if isval('ssh_port22','CLOSED'): issues.append('sshd is not listening on port 22.')
    if isval('password_auth','NO'): issues.append('Password authentication is disabled.')
    if isval('root_login','NO'): issues.append('Root SSH login is disabled.')
    if isval('dns','FAIL') or isval('dns_google','FAIL'): issues.append('Guest DNS resolution is failing.')
    if isval('ping_ip','FAIL') and isval('https','FAIL'): issues.append('Guest has no working outbound network path.')
    if isval('pinggy_tcp','FAIL'): issues.append('Guest cannot reach Pinggy TCP/443.')
    if backend != 'kvm' and isval('pinggy_sup','STOPPED'): issues.append('Pinggy supervisor is not running.')
    if isval('sshx','MISSING'): issues.append('SSHX is not installed.')
    pmax=str(data.get('pids_max','')).strip(); pcur=str(data.get('pids_current','')).strip()
    if pmax.isdigit() and pcur.isdigit() and int(pmax)>0 and int(pcur) >= int(pmax)*9//10: issues.append('Guest PID/thread cgroup is near exhaustion.')
    category='healthy' if not issues else ('ssh' if any('SSH' in x or 'sshd' in x for x in issues) else ('network' if any('DNS' in x or 'network' in x or 'Pinggy' in x for x in issues) else 'tunnel'))
    data.update({'ok':not issues,'issues':issues,'category':category,'raw':str(raw or '')[-5000:]})
    return data

async def _ai_connection_repair(vps: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    """Safe connection recovery pipeline: state -> network -> SSH -> tunnel -> verify."""
    cn=str(vps.get('container_name') or '')
    backend=str(vps.get('backend','lxc')).lower()
    node_id=int(vps.get('node_id') or 1)
    actions=[]
    # Always reconcile the real backend state BEFORE running guest commands.
    # Previously a stopped LXC caused the first guest exec to fail with
    # "Instance is not running", and the AI returned diagnostic_failed before it
    # ever reached its start/recovery logic.
    if backend != 'kvm':
        state=await _ai_lxc_state(cn,node_id)
        if not state.get('exists'):
            await _ai_mark_orphaned(vps, f'LXC `{cn}` is missing from node {node_id}.')
            return {'status':'orphaned','actions':actions,'detail':'LXC instance is missing.'}
        if state.get('status') not in ('running','ready'):
            await execute_lxc(cn, f'start {shlex.quote(cn)}', node_id=node_id, timeout=60)
            actions.append('Started stopped LXC')
            await asyncio.sleep(2)
            state=await _ai_lxc_state(cn,node_id)
            if state.get('status') not in ('running','ready'):
                return {'status':'stopped','actions':actions,'detail':f'LXC `{cn}` remains `{state.get("status", "unknown")}` after start.'}
    elif backend == 'kvm':
        state = str(await _run_local_process(['virsh','domstate',cn], timeout=12, check=False)).strip().lower()
        if state != 'running' and not state.endswith('running'):
            await _panel_power_action(vps, 'start')
            actions.append('Started stopped KVM')
            await asyncio.sleep(2)
    doctor=await _ai_connection_doctor(vps)
    if doctor.get('category') == 'guest_exec':
        return {'status':'diagnostic_failed','actions':actions,'detail':str(doctor.get('issues') or doctor.get('raw') or 'Guest diagnostic failed.')}
    pcur=str(doctor.get('pids_current','')).strip(); pmax=str(doctor.get('pids_max','')).strip()
    if pcur.isdigit() and pmax.isdigit() and int(pmax)>0 and int(pcur) >= int(pmax)*95//100:
        return {'status':'resource_exhausted','actions':actions,'detail':f'Guest PID limit is exhausted ({pcur}/{pmax}); refusing to spawn repair processes.'}
    issues=list(doctor.get('issues') or [])
    if any('SSH' in x or 'sshd' in x for x in issues):
        if backend == 'kvm':
            fixed=await configure_kvm_guest_ssh(cn, vps.get('root_password'))
            if not fixed.get('ok'): return {'status':'ssh_failed','actions':actions,'detail':str(fixed.get('error') or fixed.get('raw') or '')[-1200:]}
        else:
            ok,detail=await configure_ssh(cn,node_id,vps.get('root_password') or generate_strong_password(20))
            if not ok: return {'status':'ssh_failed','actions':actions,'detail':str(detail)[-1200:]}
        actions.append('SSH configuration repaired')
    if any('DNS' in x for x in issues) and backend == 'lxc':
        try:
            await _exec_guest_bash(cn,node_id,"(systemctl restart systemd-resolved 2>/dev/null || true); (systemctl restart NetworkManager 2>/dev/null || true); true",timeout=30)
            actions.append('Guest DNS resolver services refreshed')
        except Exception: pass
    if any('SSH' in x or 'sshd' in x for x in issues) and backend == 'lxc':
        try:
            await _exec_guest_bash(cn,node_id,"(systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || service ssh restart 2>/dev/null || service sshd restart 2>/dev/null || true); true",timeout=30)
        except Exception: pass
    refreshed=await _ai_connection_doctor(vps)
    if backend != 'kvm' and (not refreshed.get('ok') or not vps.get('pinggy_host') or any('Pinggy' in x or 'supervisor' in x for x in refreshed.get('issues',[]))):
        info=await start_pinggy_session(cn,node_id)
        if info:
            vps['pinggy_host']=info.get('host'); vps['pinggy_port']=info.get('port'); vps['pinggy_url']=info.get('url')
            actions.append('Pinggy tunnel rebuilt with durable auto-reconnect supervisor')
        else:
            return {'status':'tunnel_failed','actions':actions,'detail':'Pinggy supervisor could not publish a TCP endpoint. Check outbound TCP/443 and the tunnel log.'}
    elif backend == 'kvm' and not vps.get('pinggy_host'):
        try:
            host,port=await kvm_guest_pinggy_tunnel(cn,timeout=60)
            if host and port:
                vps['pinggy_host']=host; vps['pinggy_port']=port; actions.append('KVM Pinggy tunnel rebuilt')
        except Exception as exc:
            return {'status':'tunnel_failed','actions':actions,'detail':str(exc)[-1200:]}
    verify=await _ai_connection_doctor(vps)
    save_vps_data_immediate()
    return {'status':'repaired' if actions else ('healthy' if verify.get('ok') else 'connection_failed'),'actions':actions,'diagnostics':verify,'detail':None if verify.get('ok') else 'Connection checks still report failures.'}

async def _ai_repair_vps(owner_id: str, vps: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    """Autonomous allow-listed remediation for common SSH/network/tunnel failures."""
    cn = str(vps.get('container_name'))
    backend = str(vps.get('backend','lxc')).lower()
    key = cn.lower()
    now = time.monotonic()
    if not force and now - _ai_agent_last_repair.get(key, 0) < AI_AGENT_COOLDOWN:
        return {'status':'cooldown','actions':[]}
    actions=[]
    try:
        connection_result = await _ai_connection_repair(vps, force=force)
        actions.extend(connection_result.get('actions') or [])
        if connection_result.get('status') in ('orphaned','resource_exhausted','diagnostic_failed','ssh_failed','tunnel_failed','connection_failed'):
            return {'status': connection_result.get('status'), 'actions': actions, 'detail': connection_result.get('detail') or 'Connection repair incomplete.', 'diagnostics': connection_result.get('diagnostics')}
        # Database state is not authoritative. A previous crash/delete can leave
        # a VPS row marked `running` while the actual LXC is stopped or gone.
        # Never call `lxc exec` against a stopped/missing instance.
        if backend != 'kvm':
            state = await _ai_lxc_state(cn, int(vps.get('node_id') or 1))
            if not state.get('exists'):
                detail = f'LXC instance `{cn}` is missing from the node; repair skipped and record marked orphaned.'
                await _ai_mark_orphaned(vps, detail)
                return {'status':'orphaned','actions':[],'detail':detail}
            if state.get('status') not in ('running', 'ready'):
                await execute_lxc(cn, f'start {shlex.quote(cn)}', node_id=int(vps.get('node_id') or 1), timeout=60)
                await asyncio.sleep(2)
                state2 = await _ai_lxc_state(cn, int(vps.get('node_id') or 1))
                if state2.get('status') not in ('running', 'ready'):
                    return {'status':'stopped','actions':['LXC start attempted'],'detail':f'Instance state is `{state2.get("status", "unknown")}` after start.'}
                actions.append('Started stopped LXC instance')
        if backend == 'kvm':
            health = await kvm_guest_network_doctor(cn, repair=False)
            if health.get('https') != 'OK' and health.get('ping_ip') != 'OK':
                repaired = await kvm_guest_network_doctor(cn, repair=True)
                actions.append('KVM network repair')
                if repaired.get('https') != 'OK' and repaired.get('ping_ip') != 'OK':
                    return {'status':'network_failed','actions':actions,'detail':str(repaired.get('raw') or repaired.get('error') or '')[-1000:]}
            ssh = await _ai_kvm_ssh_health(cn)
            if not ssh.get('ok'):
                fixed = await configure_kvm_guest_ssh(cn, vps.get('root_password'))
                actions.append('KVM SSH authentication repair')
                if not fixed.get('ok'):
                    return {'status':'ssh_failed','actions':actions,'detail':str(fixed.get('error') or fixed.get('raw') or '')[-1000:]}
        else:
            ssh = await _ai_lxc_ssh_health(cn, int(vps.get('node_id') or 1))
            if not ssh.get('ok'):
                ok, detail = await configure_ssh(cn, int(vps.get('node_id') or 1), vps.get('root_password') or generate_strong_password(20))
                actions.append('LXC SSH authentication repair')
                if not ok:
                    return {'status':'ssh_failed','actions':actions,'detail':str(detail)[-1000:]}
        if actions:
            save_vps_data_immediate()
        _ai_agent_last_repair[key]=now
        _ai_agent_state['repairs'] += 1
        return {'status':'repaired' if actions else 'healthy','actions':actions}
    except Exception as exc:
        _ai_agent_last_repair[key]=now
        _ai_agent_state['errors'] += 1
        return {'status':'error','actions':actions,'detail':str(exc)[-1200:]}


async def vox_ai_agent_task():
    """Continuous self-healing agent with a strict allow-list of repair actions."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        if not _ai_agent_state.get('enabled', AI_AGENT_ENABLED):
            await asyncio.sleep(AI_AGENT_INTERVAL)
            continue
        try:
            async with _ai_agent_lock:
                _ai_agent_state['last_cycle']=datetime.now().isoformat()
                checked=0
                actions=[]
                for owner_id,vps in _ai_vps_records():
                    if checked >= AI_AGENT_MAX_VPS_PER_CYCLE:
                        break
                    if vps.get('suspended') or vps.get('status') not in ('running', 'ready'):
                        continue
                    checked += 1
                    result = await _ai_repair_vps(owner_id,vps,force=False)
                    if result.get('status') == 'healthy':
                        _ai_agent_state['healthy'] += 1
                    if result.get('actions'):
                        actions.append(f"{vps.get('container_name')}: " + ", ".join(result['actions']))
                    if result.get('status') in ('error','ssh_failed','network_failed','tunnel_failed'):
                        logger.warning("[VoxAI] %s: %s", vps.get('container_name'), result)
                _ai_agent_state['last_actions']=actions[-20:]
        except Exception as exc:
            _ai_agent_state['errors'] += 1
            logger.exception("[VoxAI] monitor cycle failed: %s", exc)
        await asyncio.sleep(AI_AGENT_INTERVAL)


AI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
AI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-6.1-sol').strip() or 'gpt-6.1-sol'
AI_MAX_OUTPUT = max(500, min(6000, int(os.getenv('OPENAI_MAX_OUTPUT', '3500') or 3500)))
AI_ENDPOINT = os.getenv('OPENAI_RESPONSES_URL', 'https://api.openai.com/v1/responses').strip()


def _ai_context_snapshot() -> str:
    """Build a compact, secret-redacted operational snapshot for the LLM."""
    rows = []
    host = {}
    try:
        import psutil
        vm = psutil.virtual_memory()
        du = psutil.disk_usage('/')
        host.update({
            'cpu_percent': psutil.cpu_percent(interval=None),
            'ram_percent': vm.percent,
            'disk_percent': du.percent,
            'load_1m': os.getloadavg()[0] if hasattr(os, 'getloadavg') else None,
            'bot_pid': os.getpid(),
        })
        fd_dir = Path(f'/proc/{os.getpid()}/fd')
        if fd_dir.exists():
            host['bot_open_fds'] = len(list(fd_dir.iterdir()))
    except Exception as exc:
        host['metrics_error'] = type(exc).__name__
    host['prefix'] = PREFIX
    host['ai_provider_configured'] = bool(AI_API_KEY) if 'AI_API_KEY' in globals() else False
    for owner_id, items in list(vps_data.items()):
        for v in items[:30]:
            rows.append({
                'id': v.get('id'), 'container': v.get('container_name'),
                'backend': v.get('backend', 'lxc'), 'status': v.get('status'),
                'node_id': v.get('node_id', 1), 'ipv4': v.get('ipv4'),
                'ssh_ready': v.get('ssh_ready'), 'pinggy': v.get('pinggy_host'),
                'ram': v.get('ram'), 'cpu': v.get('cpu'), 'storage': v.get('storage'),
            })
    return json.dumps({'bot': BOT_NAME, 'prefix': PREFIX, 'host': host, 'vps': rows, 'ai_agent': _ai_agent_state}, ensure_ascii=False, default=str)[:12000]


def _redact_ai_text(value: str) -> str:
    text = str(value or '')
    text = re.sub(r'(?i)(discord[_ -]?token|bot[_ -]?token|openai[_ -]?api[_ -]?key|authorization)\s*[:=]\s*\S+', r'\1=[REDACTED]', text)
    text = re.sub(r'(?i)(password|passwd|secret)\s*[:=]\s*[^\s,;]+', r'\1=[REDACTED]', text)
    return text[:16000]


async def _call_llm_ai(question: str) -> Optional[str]:
    if not AI_API_KEY:
        return None
    payload = {
        'model': AI_MODEL,
        'instructions': (
            'You are AxionHost Ops AI. Help diagnose Discord VPS hosting, LXD/LXC, KVM, SSH, '
            'networking, Pinggy/SSH tunnels, SQLite, systemd and Python bot problems. '
            'Use the supplied operational snapshot. Never invent a successful repair. '
            'Never expose secrets. Recommend bounded, reversible commands. Do not instruct the user '
            'to delete VPS/DB data unless they explicitly request destructive cleanup.'
        ),
        'input': _redact_ai_text(question) + '\n\nOPERATIONAL SNAPSHOT:\n' + _redact_ai_text(_ai_context_snapshot()),
        'max_output_tokens': AI_MAX_OUTPUT,
    }
    headers = {'Authorization': f'Bearer {AI_API_KEY}', 'Content-Type': 'application/json'}
    try:
        response = await asyncio.to_thread(requests.post, AI_ENDPOINT, headers=headers, json=payload, timeout=45)
        if response.status_code >= 400:
            logger.warning('[AI] provider returned HTTP %s: %s', response.status_code, _redact_ai_text(response.text[:500]))
            return None
        data = response.json()
        # Responses API exposes output_text; keep a fallback parser for compatible gateways.
        text = data.get('output_text')
        if not text:
            parts = []
            for item in data.get('output', []) or []:
                for content in item.get('content', []) or []:
                    if content.get('type') in ('output_text', 'text') and content.get('text'):
                        parts.append(content['text'])
            text = '\n'.join(parts)
        return _redact_ai_text(text).strip()[:12000] if text else None
    except Exception as exc:
        logger.warning('[AI] provider call failed: %s', exc)
        return None


@bot.command(name='prefix', aliases=['get-prefix', 'prefix-info'])
async def show_prefix(ctx):
    """Show the currently active command prefix."""
    embed = create_info_embed("⌨️ Command Prefix", f"Current prefix: `{PREFIX}`\nExample: `{PREFIX}help`")
    embed.set_footer(text="Prefix is stored in SQLite and survives bot restarts.")
    await ctx.send(embed=embed)


@bot.command(name='set-prefix', aliases=['setprefix', 'change-prefix'])
@is_admin()
async def set_prefix_command(ctx, *, new_prefix: str = ''):
    """Change the bot command prefix at runtime and persist it."""
    global PREFIX
    try:
        new_prefix = _normalize_prefix(new_prefix)
    except ValueError as exc:
        await ctx.send(embed=create_error_embed("Invalid Prefix", str(exc)))
        return

    old_prefix = PREFIX
    if new_prefix == old_prefix:
        await ctx.send(embed=create_info_embed("Prefix Unchanged", f"The current prefix is already `{old_prefix}`."))
        return

    try:
        set_setting('bot_prefix', new_prefix)
        PREFIX = new_prefix
        try:
            await record_audit_event(
                'bot', 'prefix_changed',
                f'Prefix changed from {old_prefix!r} to {new_prefix!r}',
                user_id=str(ctx.author.id), announce=False
            )
        except Exception:
            logger.exception('Failed to write prefix audit log')
        await ctx.send(embed=create_success_embed(
            "Prefix Updated",
            f"Command prefix changed from `{old_prefix}` to `{new_prefix}`.\n\n"
            f"Use `{new_prefix}help` for the command list."
        ))
    except Exception as exc:
        logger.exception('Prefix update failed')
        await ctx.send(embed=create_error_embed("Prefix Update Failed", str(exc)[:1000]))


@bot.command(name='ai')
@commands.cooldown(2, 20, commands.BucketType.user)
async def ai_assistant(ctx, *, question: str = ''):
    """Context-aware AI operations assistant. LLM is optional; local diagnostics always remain available."""
    if not question.strip():
        await ctx.send(embed=create_info_embed('🧠 AxionHost AI', f'Use `{PREFIX}ai <problem>` for diagnosis, repair guidance and safe commands.'))
        return
    async with ctx.typing():
        answer = await _call_llm_ai(question)
        if not answer:
            # Safe local fallback when no API key/provider is configured.
            q = question.lower()
            hints = []
            if 'too many open files' in q:
                hints.append('Host/container file-descriptor exhaustion detected. Check `ulimit -n`, `/proc/sys/fs/file-nr`, inotify limits and the bot process FD count before restarting services.')
            if 'instance is not running' in q or 'lxc' in q:
                hints.append('Verify the real LXC state with `lxc list --all-projects`; if DB says running but LXC is stopped, start the exact instance before any `lxc exec`.')
            if 'audit_logs' in q or 'no such table' in q:
                hints.append('Run the bot once after the v3 migration; it creates the missing `audit_logs` table without deleting existing VPS data.')
            if 'pinggy' in q or 'tunnel' in q:
                hints.append('Verify guest SSH on port 22, outbound TCP/443 and the tunnel process/log before attempting reconnect.')
            answer = '\n'.join(f'• {h}' for h in hints) or 'No local rule matched this issue. Configure OPENAI_API_KEY for full context-aware AI analysis.'
        embed = create_info_embed('🧠 AxionHost AI', answer[:4000])
        embed.set_footer(text=f'AxionHost AI • model: {AI_MODEL if AI_API_KEY else "local-safe-fallback"}')
        await ctx.send(embed=embed)


@bot.command(name='ai-check')
@is_admin()
async def ai_check(ctx):
    """Run a bounded read-only host/bot health check for AI-assisted operations."""
    checks = []
    try:
        import psutil
        vm = psutil.virtual_memory()
        du = psutil.disk_usage('/')
        checks.append(f"CPU: `{psutil.cpu_percent(interval=0.2):.1f}%`")
        checks.append(f"RAM: `{vm.percent:.1f}%`")
        checks.append(f"Disk `/`: `{du.percent:.1f}%`")
        fd_path = Path(f'/proc/{os.getpid()}/fd')
        if fd_path.exists():
            checks.append(f"Bot FDs: `{len(list(fd_path.iterdir()))}`")
    except Exception as exc:
        checks.append(f"Host metrics: unavailable (`{type(exc).__name__}`)")
    checks.append(f"Prefix: `{PREFIX}`")
    checks.append(f"AI provider: `{AI_MODEL if AI_API_KEY else 'local-safe-fallback'}`")
    checks.append(f"VPS records: `{sum(len(v) for v in vps_data.values())}`")
    checks.append(f"AI agent: `{'enabled' if _ai_agent_state.get('enabled') else 'disabled'}`")
    embed = create_info_embed("🧠 AxionHost AI System Check", "\n".join(f"• {item}" for item in checks))
    embed.set_footer(text="Read-only check • no VPS/DB changes were made")
    await ctx.send(embed=embed)


@bot.command(name='system-health', aliases=['health', 'host-health'])
@is_admin()
async def system_health(ctx):
    """Read-only host/runtime health report."""
    lines = []
    try:
        import psutil
        vm = psutil.virtual_memory()
        du = psutil.disk_usage('/')
        cpu = psutil.cpu_percent(interval=0.2)
        lines += [
            f"CPU: `{cpu:.1f}%`",
            f"RAM: `{vm.percent:.1f}%` ({vm.available / (1024**3):.1f} GiB free)",
            f"Disk: `{du.percent:.1f}%` ({du.free / (1024**3):.1f} GiB free)",
        ]
        try:
            load = os.getloadavg()
            lines.append(f"Load: `{load[0]:.2f} / {load[1]:.2f} / {load[2]:.2f}`")
        except OSError:
            pass
    except Exception as exc:
        lines.append(f"Host metrics unavailable: `{type(exc).__name__}`")
    try:
        fd_dir = Path(f'/proc/{os.getpid()}/fd')
        if fd_dir.exists():
            fd_count = len(list(fd_dir.iterdir()))
            lines.append(f"Bot file descriptors: `{fd_count}`")
    except Exception:
        pass
    lines += [
        f"Discord latency: `{round(bot.latency * 1000)}ms`",
        f"Prefix: `{PREFIX}`",
        f"Database: `{DB_PATH}`",
        f"VPS records: `{sum(len(v) for v in vps_data.values())}`",
        f"LXC binary: `{LXC_CMD}`",
    ]
    embed = create_info_embed('🩺 AxionHost System Health', '\n'.join('• ' + x for x in lines))
    embed.set_footer(text='Read-only • no VPS or database changes')
    await ctx.send(embed=embed)


@bot.command(name='db-health', aliases=['database-health'])
@is_admin()
async def db_health(ctx):
    """Validate the SQLite schema and WAL mode without modifying VPS data."""
    required = {'admins', 'nodes', 'vps', 'settings', 'audit_logs'}
    try:
        conn = get_db()
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {str(r[0]) for r in rows}
        journal = conn.execute('PRAGMA journal_mode').fetchone()[0]
        integrity = conn.execute('PRAGMA quick_check').fetchone()[0]
        vps_count = conn.execute('SELECT COUNT(*) FROM vps').fetchone()[0] if 'vps' in tables else 0
        conn.close()
        missing = sorted(required - tables)
        status = '🟢 HEALTHY' if not missing and str(integrity).lower() == 'ok' else '🟡 NEEDS ATTENTION'
        body = [f'**Status:** {status}', f'**Journal:** `{journal}`', f'**Integrity:** `{integrity}`', f'**VPS rows:** `{vps_count}`']
        body.append('**Missing tables:** `None`' if not missing else '**Missing tables:** `' + ', '.join(missing) + '`')
    except Exception as exc:
        body = [f'**Status:** 🔴 ERROR', f'`{type(exc).__name__}: {str(exc)[:700]}`']
    await ctx.send(embed=create_info_embed('🗄️ Database Health', '\n'.join(body)))


@bot.command(name='runtime-info', aliases=['bot-stats', 'runtime'])
async def runtime_info(ctx):
    """Show safe runtime information useful for support/debugging."""
    total_vps = sum(len(v) for v in vps_data.values())
    embed = create_info_embed('⚙️ AxionHost Runtime', 'Current bot runtime and configuration summary.')
    add_field(embed, 'Version', f'`{BOT_VERSION}`', True)
    add_field(embed, 'Latency', f'`{round(bot.latency * 1000)}ms`', True)
    add_field(embed, 'Prefix', f'`{PREFIX}`', True)
    add_field(embed, 'VPS', f'`{total_vps}`', True)
    add_field(embed, 'AI', '`Cloud + local fallback`' if AI_API_KEY else '`Local safe fallback`', True)
    add_field(embed, 'LXC', f'`{LXC_CMD}`', True)
    await ctx.send(embed=embed)


@bot.command(name='ai-status')
@is_admin()
async def ai_status(ctx):
    s=_ai_agent_state
    embed=create_info_embed("🧠 VoxAI Recovery Agent", "Autonomous VPS health monitoring and allow-listed recovery.")
    add_field(embed,"Status","🟢 ENABLED" if s.get('enabled') else "🔴 DISABLED",True)
    add_field(embed,"Interval",f"{AI_AGENT_INTERVAL}s",True)
    add_field(embed,"Cooldown",f"{AI_AGENT_COOLDOWN}s",True)
    add_field(embed,"Last Cycle",str(s.get('last_cycle') or 'Not started')[-1024:],False)
    add_field(embed,"Repairs",str(s.get('repairs',0)),True)
    add_field(embed,"Errors",str(s.get('errors',0)),True)
    acts=s.get('last_actions') or []
    add_field(embed,"Recent Actions","\n".join(acts[-8:]) if acts else "No repairs needed.",False)
    await ctx.send(embed=embed)


@bot.command(name='ai-agent')
@is_admin()
async def ai_agent_control(ctx, action: str = None):
    action=(action or 'status').lower()
    if action in ('on','enable','start'):
        _ai_agent_state['enabled']=True
        try: set_setting('ai_agent_enabled', '1')
        except Exception: logger.exception('Could not persist AI agent state')
        await ctx.send(embed=create_success_embed("🧠 VoxAI Enabled",f"Automatic health monitoring is now enabled. Checks run every {AI_AGENT_INTERVAL}s."))
    elif action in ('off','disable','stop'):
        _ai_agent_state['enabled']=False
        try: set_setting('ai_agent_enabled', '0')
        except Exception: logger.exception('Could not persist AI agent state')
        await ctx.send(embed=create_warning_embed("🧠 VoxAI Disabled","Automatic recovery is paused."))
    elif action == 'status':
        await ai_status(ctx)
    else:
        await ctx.send(embed=create_error_embed("Invalid AI Agent Action",f"Use `{PREFIX}ai-agent on|off|status`."))


@bot.command(name='connection-ai', aliases=['connection-fix','ai-connect','connect-ai'])
@is_admin()
async def connection_ai(ctx, vps_ref: str):
    """Deep connection doctor + safe self-healing for SSH/Pinggy/SSHX/network."""
    vps = resolve_vps_reference(vps_ref)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'No VPS `{vps_ref}` was found.'))
        return
    await ctx.send(embed=create_info_embed('🧠🔌 Connection AI', f'Diagnosing `{vps.get("container_name")}`: LXD → SSH → DNS → route → HTTPS → Pinggy → SSHX.'))
    result = await _ai_connection_repair(vps, force=True)
    diag = result.get('diagnostics') or {}
    lines = [f"**Status:** `{result.get('status','unknown')}`"]
    if result.get('actions'):
        lines.append('**Repairs:**\n' + '\n'.join(f'• {x}' for x in result['actions'][-10:]))
    issues = diag.get('issues') or []
    if issues:
        lines.append('**Remaining issues:**\n' + '\n'.join(f'• {x}' for x in issues[-10:]))
    if diag:
        lines.append(f"**SSH:** `{diag.get('ssh_service','unknown')}` • **22:** `{diag.get('ssh_port22','unknown')}` • **DNS:** `{diag.get('dns','unknown')}` • **HTTPS:** `{diag.get('https','unknown')}` • **Pinggy:** `{diag.get('pinggy_tcp','unknown')}`")
        endpoint = diag.get('pinggy_endpoint') or vps.get('pinggy_url')
        if endpoint:
            lines.append(f"**Endpoint:** `{endpoint}`")
    if result.get('status') in ('repaired','healthy'):
        await ctx.send(embed=create_success_embed('🧠🔌 Connection AI Complete', '\n'.join(lines)[:3900]))
    else:
        await ctx.send(embed=create_warning_embed('🧠🔌 Connection AI Needs Host Action', '\n'.join(lines)[:3900]))


@bot.command(name='ai-fix')
@is_admin()
async def ai_fix(ctx, vps_id: int):
    vps=None
    owner_id=None
    for oid,item in _ai_vps_records():
        try:
            if int(item.get('id')) == int(vps_id):
                vps=item; owner_id=oid; break
        except Exception:
            continue
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found",f"No VPS with ID `{vps_id}` was found."))
        return
    await ctx.send(embed=create_info_embed("🧠 VoxAI Repair",f"Diagnosing `{vps.get('container_name')}` and applying only safe recovery actions..."))
    result=await _ai_repair_vps(owner_id,vps,force=True)
    if result.get('status') in ('repaired','healthy'):
        save_vps_data_immediate()
        desc="\n".join(result.get('actions') or ["No repair was necessary."])
        await ctx.send(embed=create_success_embed("🧠 AI Repair Complete",desc))
    else:
        detail=result.get('detail') or result.get('status') or 'Unknown failure'
        await ctx.send(embed=create_error_embed("🧠 AI Repair Incomplete",f"Actions: {', '.join(result.get('actions') or ['none'])}\n\n{detail[-1600:]}"))



# ═══════════════════════════════════════════════════════════════════════════════
# AxionHost V6 — Admin Operations + VPS AI Performance Layer
# Safe-by-default: diagnostics are read-only; optimization uses an allow-list.
# ═══════════════════════════════════════════════════════════════════════════════

_AI_GUEST_DIAG = r'''set +e
printf 'HOSTNAME='; hostname 2>/dev/null
printf 'UPTIME='; uptime -p 2>/dev/null
printf 'LOAD='; cat /proc/loadavg 2>/dev/null
printf 'RAM='; free -m 2>/dev/null | awk '/^Mem:/{print $3 "/" $2 "MB"}'
printf 'DISK='; df -P / 2>/dev/null | awk 'NR==2{print $3 "/" $2 "KB," $5}'
printf 'INODES='; df -Pi / 2>/dev/null | awk 'NR==2{print $5}'
printf 'ROOTFS='; findmnt -n -o FSTYPE / 2>/dev/null
printf 'SSH='; systemctl is-active ssh 2>/dev/null || systemctl is-active sshd 2>/dev/null
printf 'FAILED='; systemctl --failed --no-legend 2>/dev/null | wc -l
printf 'DOCKER='; systemctl is-active docker 2>/dev/null
printf 'SWAPPINESS='; sysctl -n vm.swappiness 2>/dev/null
printf 'FILEMAX='; sysctl -n fs.file-max 2>/dev/null
printf 'OPENFILES='; cat /proc/sys/fs/file-nr 2>/dev/null
printf 'PROCS='; ps -e --no-headers 2>/dev/null | wc -l
'''

_AI_SAFE_OPTIMIZE = r'''set +e
CHANGED=0
# Safe housekeeping only. Never deletes user data or VPS configuration.
if command -v systemctl >/dev/null 2>&1; then
  systemctl reset-failed >/dev/null 2>&1 || true
fi
if command -v journalctl >/dev/null 2>&1; then
  journalctl --vacuum-size=100M >/dev/null 2>&1 || true
fi
if command -v apt-get >/dev/null 2>&1; then
  apt-get clean >/dev/null 2>&1 || true
  apt-get autoclean >/dev/null 2>&1 || true
fi
# Lower swappiness only when the current value is unusually high; this is runtime-only.
if command -v sysctl >/dev/null 2>&1; then
  SW=$(sysctl -n vm.swappiness 2>/dev/null || echo 60)
  case "$SW" in ''|*[!0-9]*) SW=60;; esac
  if [ "$SW" -gt 20 ]; then
    sysctl -w vm.swappiness=10 >/dev/null 2>&1 && CHANGED=$((CHANGED+1)) || true
  fi
fi
sync
printf 'OPTIMIZE_CHANGES=%s\n' "$CHANGED"
'''

def _v6_vps_records():
    for owner_id, items in list(vps_data.items()):
        for vps in list(items or []):
            yield str(owner_id), vps

def _v6_owner_for_vps(vps):
    return str(vps.get('user_id') or vps.get('owner_id') or '')

async def _v6_guest_exec(vps, script, timeout=35):
    '''Run a bounded diagnostic/allow-listed command inside a VPS.'''
    cn = str(vps.get('container_name') or '').strip()
    if not cn:
        return {'ok': False, 'error': 'missing container name'}
    backend = str(vps.get('backend') or 'lxc').lower()
    node_id = vps.get('node_id', 1)
    if backend == 'kvm':
        # KVM guest execution is intentionally not guessed. Existing KVM SSH helpers
        # can be used by the operator; never run a host shell command against a VM name.
        return {'ok': False, 'error': 'KVM guest execution requires the configured SSH path'}
    try:
        out = await execute_lxc(cn, 'exec /bin/sh -c ' + shlex.quote(script), node_id=node_id, timeout=timeout)
        return {'ok': True, 'output': str(out or '')[-10000:]}
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {str(exc)[:1200]}'}

def _v6_parse_diag(raw):
    result={}
    for line in str(raw or '').splitlines():
        if '=' in line:
            k,v=line.split('=',1)
            result[k.strip().upper()]=v.strip()
    return result

def _v6_score(diag):
    score=100; issues=[]
    def pct(v):
        try:return float(str(v).rstrip('%'))
        except:return None
    d=pct(diag.get('DISK'))
    if d is not None and d >= 95: score-=35; issues.append('root filesystem critically full')
    elif d is not None and d >= 85: score-=20; issues.append('root filesystem usage is high')
    m=str(diag.get('RAM',''))
    try:
        used,total=m.replace('MB','').split('/')
        rp=(float(used)/float(total))*100 if float(total)>0 else 0
        if rp>=95: score-=30; issues.append('RAM usage is critically high')
        elif rp>=85: score-=15; issues.append('RAM usage is high')
    except Exception: pass
    try:
        failed=int(diag.get('FAILED','0') or 0)
        if failed>0: score-=min(20,failed*5); issues.append(f'{failed} failed systemd unit(s)')
    except Exception: pass
    ssh=str(diag.get('SSH','')).lower()
    if ssh not in ('active','running'): score-=20; issues.append('SSH service is not active')
    try:
        sw=int(diag.get('SWAPPINESS','60') or 60)
        if sw>20: score-=5; issues.append(f'swappiness={sw}')
    except Exception: pass
    return max(0,score),issues

async def _v6_analyze_vps(vps, optimize=False):
    diag_result=await _v6_guest_exec(vps,_AI_GUEST_DIAG,timeout=35)
    if not diag_result.get('ok'):
        return {'status':'unreachable','score':0,'issues':[diag_result.get('error','unknown')],'diag':{},'actions':[]}
    diag=_v6_parse_diag(diag_result.get('output',''))
    score,issues=_v6_score(diag)
    actions=[]
    if optimize and score>=0:
        opt=await _v6_guest_exec(vps,_AI_SAFE_OPTIMIZE,timeout=45)
        if opt.get('ok'):
            od=_v6_parse_diag(opt.get('output',''))
            actions.append(f"safe housekeeping completed; runtime changes={od.get('OPTIMIZE_CHANGES','0')}")
        else:
            actions.append('safe housekeeping could not be completed')
    return {'status':'healthy' if score>=90 else 'attention' if score>=65 else 'critical','score':score,'issues':issues,'diag':diag,'actions':actions}

async def _v6_ai_reason(vps, result, request=''):
    if not AI_API_KEY:
        return None
    safe={
        'vps_id':vps.get('id'),'container':vps.get('container_name'),'backend':vps.get('backend','lxc'),
        'node_id':vps.get('node_id'),'ram':vps.get('ram'),'cpu':vps.get('cpu'),'storage':vps.get('storage'),
        'analysis':result,'request':request[:1500]
    }
    return await _call_llm_ai('Analyze this single VPS operational report. Give a concise priority list, explain likely causes, and only recommend reversible/allow-listed actions. Do not claim a repair that was not executed. DATA='+json.dumps(safe,default=str))

@bot.command(name='admin-panel', aliases=['admin-help','admin-menu'])
@is_admin()
async def admin_panel(ctx):
    '''Central admin command index.'''
    body=(
        f"**Maintenance**\n`{PREFIX}maintenance on|off|status`\n\n"
        f"**Announcements**\n`{PREFIX}announce online|offline|30min|<message>`\n\n"
        f"**AI Operations**\n`{PREFIX}ai-check` • `{PREFIX}ai-status` • `{PREFIX}ai-agent on|off`\n"
        f"`{PREFIX}ai-fix <vps>` • `{PREFIX}ai-vps <vps>` • `{PREFIX}ai-optimize <vps|all>` • `{PREFIX}ai-fleet`\n\n"
        f"**System / DB**\n`{PREFIX}system-health` • `{PREFIX}db-health` • `{PREFIX}runtime-info`\n"
        f"`{PREFIX}node-health` • `{PREFIX}vps-audit-all` • `{PREFIX}db-backup` • `{PREFIX}cleanup-safe`\n\n"
        f"**Management**\nUse the existing admin commands for nodes, VPS lifecycle, slots, backups, expiration, ports and settings."
    )
    embed=create_info_embed('🛡️ AxionHost Admin Control Center',body)
    embed.set_footer(text='Admin-only • destructive operations remain separately protected')
    await ctx.send(embed=embed)

@bot.command(name='ai-vps', aliases=['vps-ai','ai-diagnose'])
@is_admin()
@commands.cooldown(2,30,commands.BucketType.user)
async def ai_vps(ctx, vps_ref: str):
    vps=resolve_vps_reference(vps_ref)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found',f'No VPS matched `{vps_ref}`.'))
        return
    async with ctx.typing():
        result=await _v6_analyze_vps(vps,False)
        reason=await _v6_ai_reason(vps,result,'diagnose and prioritize improvements')
    diag=result.get('diag',{})
    lines=[f"**Score:** `{result['score']}/100`",f"**Status:** `{result['status']}`"]
    if result.get('issues'): lines.append('**Issues:**\n'+'\n'.join('• '+x for x in result['issues'][:8]))
    lines.append(f"**Disk:** `{diag.get('DISK','unknown')}` • **RAM:** `{diag.get('RAM','unknown')}` • **SSH:** `{diag.get('SSH','unknown')}`")
    if reason: lines.append('\n**AI Priority Plan:**\n'+reason[:2500])
    embed=create_info_embed('🧠 AxionHost AI VPS Doctor','\n'.join(lines))
    embed.set_footer(text='Read-only diagnosis • no VPS configuration changed')
    await ctx.send(embed=embed)

@bot.command(name='ai-optimize', aliases=['optimize-vps','vps-optimize'])
@is_admin()
@commands.cooldown(1,60,commands.BucketType.user)
async def ai_optimize(ctx, target: str):
    '''Optimize one VPS or the complete fleet using only safe allow-listed actions.'''
    targets=[]
    if target.lower()=='all':
        targets=[v for _,v in _v6_vps_records()]
        if not targets:
            await ctx.send(embed=create_info_embed('🧠 AI Optimizer','No VPS records found.')); return
    else:
        v=resolve_vps_reference(target)
        if not v:
            await ctx.send(embed=create_error_embed('VPS Not Found',f'No VPS matched `{target}`.')); return
        targets=[v]
    await ctx.send(embed=create_info_embed('⚙️ AI Optimizer Started',f'Analyzing `{len(targets)}` VPS. Only safe allow-listed maintenance will be applied.'))
    rows=[]
    for vps in targets[:50]:
        async with ctx.typing():
            result=await _v6_analyze_vps(vps,True)
        rows.append(f"`#{vps.get('id','?')}` **{str(vps.get('container_name','?'))[:32]}** — `{result['score']}/100` — {result['status']}")
        if result.get('actions'): rows.append('  ↳ '+result['actions'][0][:120])
        await asyncio.sleep(0.2)
    try:
        await record_audit_event('ai','fleet_optimized',f'Optimized {len(targets[:50])} VPS using safe allow-list',user_id=str(ctx.author.id),announce=False)
    except Exception: pass
    embed=create_success_embed('🧠 AI Optimization Complete','\n'.join(rows)[:3900])
    embed.set_footer(text='No VPS deletion/rebuild/reinstall performed')
    await ctx.send(embed=embed)

@bot.command(name='ai-fleet', aliases=['fleet-ai','ai-all'])
@is_admin()
@commands.cooldown(1,45,commands.BucketType.user)
async def ai_fleet(ctx):
    '''Read-only fleet health overview.'''
    records=list(_v6_vps_records())
    if not records:
        await ctx.send(embed=create_info_embed('🧠 AI Fleet','No VPS records found.')); return
    healthy=attention=critical=unreachable=0; rows=[]
    for _,vps in records[:50]:
        result=await _v6_analyze_vps(vps,False)
        st=result['status']
        if st=='healthy': healthy+=1
        elif st=='attention': attention+=1
        elif st=='critical': critical+=1
        else: unreachable+=1
        rows.append(f"`#{vps.get('id','?')}` {str(vps.get('container_name','?'))[:28]} → `{result['score']}/100` {st}")
        await asyncio.sleep(0.15)
    summary=f"🟢 Healthy `{healthy}` • 🟡 Attention `{attention}` • 🔴 Critical `{critical}` • ⚫ Unreachable `{unreachable}`\n\n"+'\n'.join(rows)
    embed=create_info_embed('🧠 AxionHost AI Fleet Health',summary[:3900])
    embed.set_footer(text='Read-only fleet scan • use ai-optimize all for safe housekeeping')
    await ctx.send(embed=embed)

@bot.command(name='admin-node-health', aliases=['nodes-health-admin','nodecheck-admin'])
@is_admin()
async def node_health(ctx):
    '''Read-only health summary for configured deployment nodes.'''
    rows=[]
    for node in nodes_data.values() if isinstance(nodes_data,dict) else []:
        rows.append(str(node))
    if not rows:
        try:
            rows=[str(x) for x in get_nodes()]
        except Exception: rows=[]
    if not rows:
        rows=['No configured nodes returned by the node registry.']
    await ctx.send(embed=create_info_embed('🖥️ Node Health','\n'.join('• '+x[:500] for x in rows)[:3900]))

@bot.command(name='vps-audit-all', aliases=['audit-all','fleet-audit'])
@is_admin()
async def vps_audit_all(ctx):
    '''Fast DB-level audit of all VPS records; does not mutate them.'''
    records=list(_v6_vps_records()); problems=[]
    for owner,vps in records:
        missing=[k for k in ('id','container_name','node_id','backend') if not vps.get(k)]
        if missing: problems.append(f"#{vps.get('id','?')}: missing {', '.join(missing)}")
        if vps.get('status')=='orphaned': problems.append(f"#{vps.get('id','?')}: orphaned")
    body=f"Records: `{len(records)}`\nProblems: `{len(problems)}`\n\n"+('\n'.join('• '+x for x in problems[:30]) if problems else '🟢 No obvious database-level problems found.')
    await ctx.send(embed=create_info_embed('🔎 VPS Fleet Audit',body[:3900]))

@bot.command(name='db-backup', aliases=['backup-db','database-backup'])
@is_admin()
async def db_backup(ctx):
    '''Create a consistent SQLite backup without touching the live DB.'''
    try:
        import sqlite3, shutil
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
        dest=f'/root/vps.db.backup-{stamp}'
        src=sqlite3.connect(DB_PATH)
        out=sqlite3.connect(dest)
        src.backup(out)
        out.close(); src.close()
        size=os.path.getsize(dest)
        await ctx.send(embed=create_success_embed('💾 Database Backup Created',f'`{dest}`\nSize: `{size/1024:.1f} KiB`'))
    except Exception as exc:
        await ctx.send(embed=create_error_embed('Database Backup Failed',f'`{type(exc).__name__}: {str(exc)[:1000]}`'))

@bot.command(name='cleanup-safe', aliases=['safe-cleanup','cleanup'])
@is_admin()
async def cleanup_safe(ctx):
    '''Clean only temporary Python cache/log clutter outside VPS data.'''
    removed=0; errors=0
    candidates=['/root/__pycache__']
    import shutil
    for path in candidates:
        try:
            if os.path.isdir(path): shutil.rmtree(path); removed+=1
        except Exception: errors+=1
    await ctx.send(embed=create_success_embed('🧹 Safe Cleanup Complete',f'Removed temporary cache directories: `{removed}`\nErrors: `{errors}`\nVPS data and database were not deleted.'))

@bot.command(name='node-resource-health', aliases=['resource-health','node-resources'])
@is_admin()
async def node_resource_health(ctx, node_id: int = None):
    """Show resource/process limits that can cause LXD pthread failures."""
    nodes = get_nodes()
    if node_id is None:
        local = next((n for n in nodes if n.get('is_local')), None)
        node_id = local['id'] if local else (nodes[0]['id'] if nodes else None)
    if node_id is None:
        await ctx.send(embed=create_error_embed('No Node', 'No node is configured.'))
        return
    try:
        stats = await asyncio.wait_for(get_host_stats(node_id), timeout=20)
    except Exception as exc:
        await ctx.send(embed=create_error_embed('Node Health Failed', safe_error_summary('Resource check', exc)))
        return
    node = get_node(node_id) or {}
    if node.get('is_local'):
        def read_int(path, default=-1):
            try:
                return int(Path(path).read_text().strip())
            except Exception:
                return default
        pid_max = read_int('/proc/sys/kernel/pid_max')
        threads_max = read_int('/proc/sys/kernel/threads-max')
        tasks = subprocess.run(['ps','-eLf'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        try:
            proc_count = int(subprocess.check_output(['ps','-eLf'], text=True).count('\n') - 1)
        except Exception:
            proc_count = -1
        try:
            lxd_limit = subprocess.check_output(['systemctl','show','snap.lxd.daemon','-p','TasksCurrent','-p','TasksMax','-p','LimitNPROC'], text=True).strip().replace('\n',' | ')
        except Exception:
            lxd_limit = 'unavailable'
        detail = (f"**Node:** `{node.get('name', node_id)}`\n"
                  f"**CPU:** `{float(stats.get('cpu') or 0):.1f}%`\n"
                  f"**RAM:** `{float(stats.get('ram') or 0):.1f}%`\n"
                  f"**PID max:** `{pid_max}`\n**Threads max:** `{threads_max}`\n**Tasks/process lines:** `{proc_count}`\n"
                  f"**LXD limits:** `{lxd_limit}`\n\n"
                  "If LXD reports `pthread_create failed: Resource temporarily unavailable`, raise the node PID/Tasks/NPROC limits and reduce runaway processes before retrying.")
    else:
        detail = f"**Node:** `{node.get('name', node_id)}`\n**CPU:** `{float(stats.get('cpu') or 0):.1f}%`\n**RAM:** `{float(stats.get('ram') or 0):.1f}%`\nRemote process/PID limits must be checked on the node agent."
    await ctx.send(embed=create_info_embed('🛡️ Node Resource Health', detail))


@bot.command(name='create')
@is_admin()
async def create_vps(ctx, ram: int, cpu: int, disk: int, user: discord.Member, expiry_days: int = None):
    if ram <= 0 or cpu <= 0 or disk <= 0:
        await ctx.send(embed=create_error_embed("Invalid Specs", "RAM, CPU, and Disk must be positive integers."))
        return
    
    # Validate expiry_days if provided
    if expiry_days is not None and expiry_days <= 0:
        await ctx.send(embed=create_error_embed("Invalid Expiry Days", "Expiry days must be a positive integer."))
        return
    
    expiry_text = f" with {expiry_days} days expiry" if expiry_days else f" with {DEFAULT_VPS_EXPIRATION_DAYS} days expiry (default)"
    embed = create_info_embed("VPS Creation", f"Creating VPS for {user.mention} with {ram}GB RAM, {cpu} CPU cores, {disk}GB Disk{expiry_text}.\nSelect node below.")
    view = NodeSelectView(ram, cpu, disk, user, ctx, expiry_days)
    await ctx.send(embed=embed, view=view)

class ReinstallOSSelectView(discord.ui.View):
    def __init__(self, parent_view, container_name, owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id):
        super().__init__(timeout=300)
        self.parent_view = parent_view
        self.container_name = container_name
        self.owner_id = owner_id
        self.actual_idx = actual_idx
        self.ram_gb = ram_gb
        self.cpu = cpu
        self.storage_gb = storage_gb
        self.node_id = node_id
        self.backend = get_vps_backend(container_name)
        os_source = [o for o in OS_OPTIONS if (self.backend != 'kvm' or o['value'] in KVM_SUPPORTED_IMAGES)]
        self.select = discord.ui.Select(
            placeholder="Select an OS for the reinstall",
            options=[discord.SelectOption(label=o["label"], value=o["value"]) for o in os_source]
        )
        self.select.callback = self.select_os
        self.add_item(self.select)

    async def select_os(self, interaction: discord.Interaction):
        if str(getattr(self, 'backend', 'lxc')).lower() == 'kvm':
            await interaction.response.send_message(
                embed=create_error_embed('KVM Reinstall Disabled', 'KVM VPS creation/reinstallation is disabled. Your existing KVM VPS was not changed. Use LXC for new deployments.'),
                ephemeral=True
            )
            return
        os_version = self.select.values[0]
        self.select.disabled = True
        creating_embed = create_info_embed("Reinstalling VPS", f"Deploying {os_version} for `{self.container_name}`...")
        await interaction.response.edit_message(embed=creating_embed, view=self)
        ram_mb = self.ram_gb * 1024
        
        # Generate new password for reinstall
        new_password = generate_strong_password()
        
        try:
            # Validate before destructive reinstall. KVM and LXC use different image paths.
            target_vps = vps_data[self.owner_id][self.actual_idx]
            if self.backend == 'kvm':
                if os_version not in KVM_SUPPORTED_IMAGES:
                    raise RuntimeError(f"KVM does not support `{os_version}` yet.")
                await execute_kvm(self.container_name, f"delete {self.container_name}", self.node_id)
                kvm_reinstall_info = await create_kvm_instance(self.container_name, os_version, self.node_id, self.ram_gb, self.cpu, self.storage_gb, new_password, target_vps.get('cpu_model') or KVM_CPU_MODE)
                kvm_reinstall_info['networks'] = await wait_for_kvm_network(self.container_name, timeout=30)
                kvm_ssh = await configure_kvm_guest_ssh(self.container_name, new_password)
                if not kvm_ssh.get('ok'):
                    raise RuntimeError("KVM SSH setup failed after reinstall: " + str(kvm_ssh.get('error') or kvm_ssh.get('raw') or '')[-1600:])
            else:
                await validate_os_image(os_version, self.node_id)
                await resolve_storage_pool(self.node_id)
                await safe_delete_instance(self.container_name, self.node_id)
                await create_instance_from_image(self.container_name, os_version, self.node_id)
                await execute_lxc(self.container_name, f"config set {self.container_name} limits.memory {ram_mb}MB", node_id=self.node_id)
                await execute_lxc(self.container_name, f"config set {self.container_name} limits.cpu {self.cpu}", node_id=self.node_id)
                await execute_lxc(self.container_name, f"config device set {self.container_name} root size={self.storage_gb}GB", node_id=self.node_id)
                await apply_lxc_config(self.container_name, self.node_id)
                await execute_lxc(self.container_name, f"start {self.container_name}", node_id=self.node_id)
                await apply_internal_permissions(self.container_name, self.node_id)
                success, result = await configure_ssh(self.container_name, self.node_id, new_password)
                if not success:
                    logger.warning(f"SSH configuration partially failed: {result}")
                if HOST_MOTD:
                    try:
                        await execute_lxc(self.container_name, f"exec {self.container_name} -- bash -c {shlex.quote(HOST_MOTD)}", node_id=self.node_id)
                    except Exception as e:
                        logger.warning(f"HOST_MOTD execution failed for {self.container_name}: {e}")
                await recreate_port_forwards(self.container_name)
            target_vps["os_version"] = os_version
            target_vps["status"] = "running"
            target_vps["suspended"] = False
            target_vps["created_at"] = datetime.now().isoformat()
            target_vps["root_password"] = new_password
            config_str = f"{self.ram_gb}GB RAM / {self.cpu} CPU / {self.storage_gb}GB Disk"
            target_vps["config"] = config_str
            if self.backend == 'kvm':
                target_vps["cpu_model"] = kvm_reinstall_info.get("cpu_model", "libvirt-default")
                target_vps["networks"] = kvm_reinstall_info.get("networks", {})
            # IMPORTANT: Preserve expiration date during reinstall
            # If expiration_date is missing or None, set it to current expiration + DEFAULT_VPS_EXPIRATION_DAYS
            if not target_vps.get('expiration_date'):
                # No expiration was set, so set it now
                target_vps['expiration_date'] = (datetime.now() + timedelta(days=DEFAULT_VPS_EXPIRATION_DAYS)).isoformat()
            # If expiration_date exists, keep it as is - don't reset on reinstall
            save_vps_data_immediate()
            success_embed = create_success_embed("Reinstall Complete", f"VPS `{self.container_name}` has been successfully reinstalled!")
            add_field(success_embed, "Resources", f"**RAM:** {self.ram_gb}GB\n**CPU:** {self.cpu} Cores\n**Storage:** {self.storage_gb}GB", False)
            add_field(success_embed, "OS", os_version, True)
            add_field(success_embed, "SSH Configuration", "✅ Configured (PasswordAuth enabled)\n🔐 New password generated and sent via DM", True)
            add_field(success_embed, "Virtualization", f"Backend: `{self.backend.upper()}`\nCPU: `{self.cpu} vCPU`\nCPU model: `{target_vps.get('cpu_model') or KVM_CPU_MODE if self.backend == 'kvm' else 'host-shared'}`\nSeparate guest kernel: `{self.backend == 'kvm'}`", False)
            add_field(success_embed, "Disk Note", "Run `sudo resize2fs /` inside VPS if needed to expand filesystem.", False)
            await interaction.followup.send(embed=success_embed, ephemeral=True)
            
            # Send DM to owner with new password
            try:
                owner = await bot.fetch_user(int(self.owner_id))
                dm_embed = create_success_embed("🔄 VPS Reinstalled Successfully!", f"Your VPS `{self.container_name}` is ready with a new operating system!")
                
                # VPS Details Section
                vps_details = f"""
**Container:** `{self.container_name}`
**New OS:** {os_version}
**Configuration:** {self.ram_gb}GB RAM / {self.cpu} CPU / {self.storage_gb}GB Disk
**Status:** 🟢 Running
**Reinstalled:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                add_field(dm_embed, "📊 VPS Details", vps_details.strip(), False)
                
                # Get all network interfaces - with timeout to prevent hanging
                                # Start Pinggy tunnel after reinstall
                pinggy_raw = None if self.backend == 'kvm' else await start_pinggy_tunnel(self.container_name, self.node_id)
                pinggy_host, pinggy_port = parse_pinggy_url(pinggy_raw) if pinggy_raw else (None, None)

                # Store tunnel info
                target_vps['pinggy_host'] = pinggy_host
                target_vps['pinggy_port'] = pinggy_port

                # Get internal network IPs
                try:
                    networks = await asyncio.wait_for(get_kvm_networks(self.container_name), timeout=5.0) if self.backend == 'kvm' else await asyncio.wait_for(
                        get_container_networks(self.container_name, self.node_id),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout getting networks for {self.container_name}")
                    networks = {}

                # Build SSH info showing BOTH tunnel and internal IPs
                if pinggy_host and pinggy_port:
                    ssh_access_info = (
                        f"**🌐 Pinggy Tunnel (Recommended):**\n"
                        f"`ssh root@{pinggy_host} -p {pinggy_port}`\n\n"
                    )
                    if networks:
                        ssh_access_info += "**🖥️ Internal Network IPs:**\n"
                        for interface, ip in sorted(networks.items()):
                            ssh_access_info += f"└─ **{interface}:** `ssh root@{ip}`\n"
                        ssh_access_info += "\n"
                        ssh_access_info += (
                        f"**🔑 New Login Credentials:**\n"
                        f"**Username:** `root`\n"
                        f"**Password:** `{new_password}`\n\n"
                        f"⚠️ Save this password securely!\n"
                        f"🔄 If tunnel disconnects, use `{PREFIX}manage` → **🔄 Reconnect Tunnel**."
                    )
                else:
                    if networks:
                        ssh_access_info = "**🖥️ Available Connection Points:**\n"
                        for interface, ip in sorted(networks.items()):
                            ssh_access_info += f"└─ **{interface}:** `ssh root@{ip}`\n"
                        ssh_access_info += (
                            f"\n**🔑 New Login Credentials:**\n"
                            f"**Username:** `root`\n"
                            f"**Password:** `{new_password}`\n\n"
                            f"⚠️ Save this password securely!"
                        )
                    else:
                        ssh_access_info = (
                            f"**🔑 New Login Credentials:**\n"
                            f"**Username:** `root`\n"
                            f"**Password:** `{new_password}`\n\n"
                            f"📡 Network initializing, check in a few seconds.\n"
                            f"Use `{PREFIX}manage` → **🔄 Reconnect Tunnel** for SSH access.\n\n"
                            f"⚠️ Save this password securely!"
                        )

                add_field(dm_embed, "🔐 SSH Credentials & Access", ssh_access_info, False)
                
                # SSH Features
                features_info = """✅ **SSH:** Password authentication enabled
✅ **SFTP:** File transfer available
✅ **Root:** Full root access granted
✅ **Ports:** All ports available for forwarding
✅ **Docker:** Nesting, privileged mode, FUSE enabled
✅ **Fresh:** Clean OS installation ready to use"""
                add_field(dm_embed, "⚙️ Features & Capabilities", features_info, False)
                
                # Support Section
                support_info = f"""**Need Help?**
• Use `{PREFIX}manage` to manage your VPS
• Click 🔐 in manage to regenerate password
• Contact admin for issues or upgrades
• Your data from the previous OS has been wiped"""
                add_field(dm_embed, "📞 Support & Management", support_info, False)
                
                await owner.send(embed=dm_embed)
            except Exception as e:
                logger.warning(f"Failed to send reinstall DM to {self.owner_id}: {e}")
            
            self.stop()
        except Exception as e:
            error_embed = create_error_embed("Reinstall Failed", f"Error: {str(e)}")
            await interaction.followup.send(embed=error_embed, ephemeral=True)
            self.stop()


async def _panel_guest_exec(vps: Dict[str, Any], command: str, timeout: int = 30) -> str:
    """Execute a guest-side command through the correct backend."""
    name = str(vps.get('container_name') or '')
    backend = str(vps.get('backend', 'lxc')).lower()
    if not name:
        raise RuntimeError('VPS has no container/VM name.')
    if backend == 'kvm':
        return await kvm_guest_exec(name, command, timeout=timeout)
    return await execute_lxc(name, f"exec {name} -- sh -c {shlex.quote(command)}",
                             node_id=int(vps.get('node_id', 1)), timeout=timeout)


def _panel_sync_vps_record(owner_id: str, actual_idx: int) -> Optional[Dict[str, Any]]:
    try:
        return vps_data[str(owner_id)][actual_idx]
    except (KeyError, IndexError, TypeError):
        return None


def _panel_backup_name() -> str:
    return f"panel-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


async def _panel_delete_vps(owner_id: str, actual_idx: int) -> str:
    """Delete a VPS from the backend and persistent database after UI confirmation."""
    owner_id = str(owner_id)
    target = _panel_sync_vps_record(owner_id, actual_idx)
    if not target:
        raise RuntimeError('VPS record no longer exists. Refresh the VPS manager.')
    name = str(target['container_name'])
    node_id = int(target.get('node_id', 1))
    vps_id = target.get('id', '?')
    try:
        await execute_lxc(name, f"delete {name} --force", node_id=node_id, timeout=180)
        backend_result = 'Backend deleted.'
    except Exception as exc:
        low = str(exc).lower()
        if any(x in low for x in ('not found', 'does not exist', 'no such container', 'domain not found')):
            backend_result = 'Backend object was already absent; database cleanup completed.'
        else:
            raise RuntimeError(f'Backend deletion failed: {str(exc)[:900]}')

    conn = get_db()
    try:
        conn.execute('DELETE FROM vps WHERE container_name = ?', (name,))
        conn.execute('DELETE FROM port_forwards WHERE vps_container = ?', (name,))
        conn.commit()
    finally:
        conn.close()

    try:
        del vps_data[owner_id][actual_idx]
        if not vps_data[owner_id]:
            del vps_data[owner_id]
    except (KeyError, IndexError):
        pass
    save_vps_data_immediate()
    return f"VPS `#{vps_id}` `{name}` deleted. {backend_result}"

async def _panel_power_action(vps: Dict[str, Any], action: str) -> str:
    """Unified LXC/KVM power operation with post-start KVM network repair."""
    name = str(vps.get('container_name') or '')
    node_id = int(vps.get('node_id', 1))
    backend = str(vps.get('backend', 'lxc')).lower()
    if not name:
        raise RuntimeError('VPS name is missing.')
    if backend == 'kvm':
        if action == 'start':
            # Repair/verify the host network BEFORE booting the VM. Starting a
            # guest first and fixing libvirt afterwards caused false
            # 'no internet' states on cold boots.
            if KVM_NETWORK_REPAIR_ON_START:
                await ensure_kvm_network()
            state = (await _run_local_process(['virsh','domstate',name], timeout=15, check=False)).strip().lower()
            if state != 'running':
                await _run_local_process(['virsh','start',name], timeout=120)
            await asyncio.sleep(3)
            nets = await wait_for_kvm_network(name, timeout=KVM_GUEST_NETWORK_TIMEOUT)
            if not nets:
                doctor = await kvm_guest_network_doctor(name, repair=True)
                nets = await wait_for_kvm_network(name, timeout=30)
                if not nets:
                    raise RuntimeError('KVM VM started, but no IPv4/DHCP lease was obtained. Network diagnostic: ' + str(doctor.get('raw') or doctor.get('error') or 'unknown')[-1400:])
            await configure_kvm_guest_ssh(name, vps.get('root_password'))
            return f'KVM started. IPv4: {", ".join(nets.values())}'
        if action == 'stop':
            await _run_local_process(['virsh','shutdown',name], timeout=30, check=False)
            return 'KVM shutdown requested.'
        if action == 'restart':
            await _run_local_process(['virsh','reboot',name], timeout=60, check=False)
            await asyncio.sleep(3)
            if KVM_NETWORK_REPAIR_ON_START:
                await ensure_kvm_network()
            nets = await wait_for_kvm_network(name, timeout=KVM_GUEST_NETWORK_TIMEOUT)
            if not nets:
                await kvm_guest_network_doctor(name, repair=True)
                nets = await wait_for_kvm_network(name, timeout=30)
            if not nets:
                raise RuntimeError('KVM rebooted but guest networking did not recover.')
            return f'KVM restarted. IPv4: {", ".join(nets.values())}'
        raise RuntimeError(f'Unsupported power action: {action}')
    if action == 'start':
        await execute_lxc(name, f'start {name}', node_id=node_id, timeout=120)
        await apply_internal_permissions(name, node_id)
        await recreate_port_forwards(name)
        return 'LXC started.'
    if action == 'stop':
        await execute_lxc(name, f'stop {name}', node_id=node_id, timeout=120)
        return 'LXC stopped.'
    if action == 'restart':
        await execute_lxc(name, f'restart {name}', node_id=node_id, timeout=120)
        await apply_internal_permissions(name, node_id)
        await recreate_port_forwards(name)
        return 'LXC restarted.'
    raise RuntimeError(f'Unsupported power action: {action}')

async def _ensure_vps_running_for_action(vps: Dict[str, Any], reason: str = 'this action') -> Dict[str, Any]:
    """Reconcile real backend state and safely start a stopped VPS when an action needs a running guest."""
    name = str(vps.get('container_name') or '')
    node_id = int(vps.get('node_id') or 1)
    backend = str(vps.get('backend', 'lxc')).lower()
    if not name:
        raise RuntimeError('VPS name is missing.')
    if backend == 'kvm':
        state = str(await _run_local_process(['virsh', 'domstate', name], timeout=12, check=False)).strip().lower()
        running = state == 'running' or state.endswith('running')
        actual = 'running' if running else (state or 'unknown')
    else:
        info = await _ai_lxc_state(name, node_id)
        if not info.get('exists'):
            raise RuntimeError(f'VPS `{name}` is missing from node {node_id}; the database record is stale/orphaned.')
        actual = str(info.get('status') or 'unknown').lower()
        running = actual in ('running', 'ready')
    vps['status'] = 'running' if running else ('stopped' if actual in ('stopped', 'shut down', 'shutoff') else actual)
    if running:
        return {'started': False, 'state': actual}
    if actual in ('orphaned', 'missing'):
        raise RuntimeError(f'VPS `{name}` is not available on the backend.')
    await _panel_power_action(vps, 'start')
    await asyncio.sleep(2)
    if backend == 'kvm':
        state2 = str(await _run_local_process(['virsh', 'domstate', name], timeout=12, check=False)).strip().lower()
        ok = state2 == 'running' or state2.endswith('running')
    else:
        info2 = await _ai_lxc_state(name, node_id)
        ok = str(info2.get('status') or '').lower() in ('running', 'ready')
    if not ok:
        raise RuntimeError(f'VPS `{name}` did not reach running state after the automatic start for {reason}.')
    vps['status'] = 'running'
    save_vps_data_immediate()
    return {'started': True, 'state': 'running'}


class ManageView(discord.ui.View):
    def __init__(self, user_id, vps_list, is_shared=False, owner_id=None, is_admin=False, actual_index: Optional[int] = None):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.vps_list = vps_list[:]
        self.selected_index = None
        self.is_shared = is_shared
        self.owner_id = owner_id or user_id
        self.is_admin = is_admin
        self.actual_index = actual_index
        self.indices = list(range(len(vps_list)))
        self._embed_cache = None   # ← cache so get_initial_embed() always works

        if self.is_shared and self.actual_index is None:
            raise ValueError("actual_index required for shared views")

        if len(vps_list) > 1:
            options = [
                discord.SelectOption(
                    label=f"VPS {i+1} ({v.get('config', 'Custom')})",
                    description=f"Status: {v.get('status', 'unknown')}",
                    value=str(i)
                ) for i, v in enumerate(vps_list)
            ]
            self.select = discord.ui.Select(placeholder="Select a VPS to manage", options=options)
            self.select.callback = self.select_vps
            self.add_item(self.select)
        else:
            # Single VPS — select it immediately and show buttons
            self.selected_index = 0
            self.add_action_buttons()

    async def get_initial_embed(self):
        """Always returns a valid embed — builds it if not cached yet."""
        if self._embed_cache is not None:
            return self._embed_cache

        if self.selected_index is not None:
            # Single VPS path
            self._embed_cache = await self.create_vps_embed(self.selected_index)
        else:
            # Multi-VPS path — show selection list
            embed = create_embed("VPS Management", "Select a VPS from the dropdown menu below.", 0x1a1a1a)
            add_field(embed, "Available VPS",
                "\n".join([f"**VPS {i+1}:** `{v['container_name']}` - Status: `{v.get('status', 'unknown').upper()}`"
                           for i, v in enumerate(self.vps_list)]), False)
            self._embed_cache = embed

        return self._embed_cache

    async def create_vps_embed(self, index):
        vps = self.vps_list[index]
        node = get_node(vps['node_id'])
        node_name = node['name'] if node else "Unknown"
        status = vps.get('status', 'unknown')
        suspended = vps.get('suspended', False)
        whitelisted = vps.get('whitelisted', False)
        # Reconcile stale DB power state for local LXC so the panel does not show
        # RUNNING while the real instance is stopped. Keep this read-only here.
        if str(vps.get('backend', 'lxc')).lower() != 'kvm':
            node_for_status = get_node(vps.get('node_id'))
            if node_for_status and bool(node_for_status.get('is_local')):
                try:
                    real_state = await _ai_lxc_state(str(vps.get('container_name')), int(vps.get('node_id') or 1))
                    if real_state.get('exists') and real_state.get('status') in ('running', 'ready', 'stopped'):
                        status = 'running' if real_state.get('status') in ('running', 'ready') else 'stopped'
                        vps['status'] = status
                except Exception:
                    pass
        status_color = 0x00ff88 if status == 'running' and not suspended else 0xffaa00 if suspended else 0xff3366
        container_name = vps['container_name']
        stats = await get_container_stats(container_name, vps['node_id'])
        status_text = f"{status.upper()}"
        if suspended:
            status_text += " (SUSPENDED)"
        if whitelisted:
            status_text += " (WHITELISTED)"
        owner_text = ""
        if self.is_admin and self.owner_id != self.user_id:
            try:
                owner_user = await bot.fetch_user(int(self.owner_id))
                owner_text = f"\n**Owner:** {owner_user.mention}"
            except:
                owner_text = f"\n**Owner ID:** {self.owner_id}"
        embed = create_embed(
            f"VPS Management - VPS {index + 1}",
            f"Managing container: `{container_name}` on node {node_name}{owner_text}",
            status_color
        )
        resource_info = f"**Configuration:** {vps.get('config', 'Custom')}\n"
        resource_info += f"**Status:** `{status_text}`\n"
        resource_info += f"**RAM:** {vps['ram']}\n"
        resource_info += f"**CPU:** {vps['cpu']} Cores\n"
        resource_info += f"**Storage:** {vps['storage']}\n"
        resource_info += f"**OS:** {vps.get('os_version', 'ubuntu:22.04')}\n"
        resource_info += f"**Uptime:** {stats['uptime']}"
        add_field(embed, "📊 Allocated Resources", resource_info, False)

        # Expiration info
        if vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            if days_remaining < 0:
                expiration_status = "🔴 EXPIRED"
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                expiration_status = "🟡 EXPIRING SOON"
            else:
                expiration_status = "🟢 ACTIVE"
            expiration_info = f"**Status:** {expiration_status}\n"
            expiration_info += f"**Expires:** {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
            expiration_info += f"**Days Left:** {max(0, days_remaining)} days"
            add_field(embed, "⏰ Expiration", expiration_info, False)
        else:
            add_field(embed, "⏰ Expiration", "No expiration date set", False)

        if suspended:
            add_field(embed, "⚠️ Suspended", "This VPS is suspended. Contact an admin to unsuspend.", False)
        if whitelisted:
            add_field(embed, "✅ Whitelisted", "This VPS is exempt from auto-suspension.", False)

        # Live stats
        cpu_usage = f"{stats.get('cpu', 0):.1f}%" if stats.get('cpu') is not None else "Unknown"
        ram_data = stats.get('ram', {})
        ram_used = ram_data.get('used', 0) if isinstance(ram_data, dict) else 0
        ram_total = ram_data.get('total', 0) if isinstance(ram_data, dict) else 0
        ram_pct = ram_data.get('pct', 0.0) if isinstance(ram_data, dict) else 0.0
        ram_str = f"{ram_used}/{ram_total} MB ({ram_pct:.1f}%)" if ram_total > 0 else "Unknown"
        disk_usage = stats.get('disk', 'Unknown')
        live_stats = f"**CPU Usage:** {cpu_usage}\n**Memory:** {ram_str}\n**Disk:** {disk_usage}"
        add_field(embed, "📈 Live Usage", live_stats, False)

        # Pinggy tunnel info
        pinggy_host = vps.get('pinggy_host')
        pinggy_port = vps.get('pinggy_port')
        if pinggy_host and pinggy_port:
            tunnel_info = (
                f"**SSH Command:**\n"
                f"`ssh root@{pinggy_host} -p {pinggy_port}`\n"
                f"**Host:** `{pinggy_host}`\n"
                f"**Port:** `{pinggy_port}`\n"
                f"**Username:** `root`\n"
                f"**Termius:** Add an SSH host with the Host, Port and Username above; use your VPS root password.\n"
                f"**Status:** 🟢 Tunnel Active\n"
                f"*(Click 🔄 Reconnect Tunnel if disconnected)*"
            )
        else:
            tunnel_info = (
                f"**Status:** 🔴 No tunnel active\n"
                f"*(Click 🔄 Reconnect Tunnel to start)*"
            )
        add_field(embed, "🌐 Pinggy SSH Tunnel", tunnel_info, False)

        ai_last = _ai_agent_last_repair.get(str(container_name).lower())
        ai_status_text = "🟢 Auto-recovery agent enabled"
        if ai_last:
            ai_status_text += f"\nLast repair attempt: `{int(time.monotonic() - ai_last)}s ago`"
        add_field(embed, "🧠 VoxAI Protection", ai_status_text, False)

        add_field(embed, "🎮 Controls", "Use the buttons below to manage your VPS", False)
        return embed

    def add_action_buttons(self):
        # Mobile-first VPS panel. Discord allows up to 5 buttons per row;
        # keeping this compact makes the manager usable on phones as well as desktop.
        if not self.is_shared and not self.is_admin:
            reinstall_button = discord.ui.Button(label="🔄 Reinstall", style=discord.ButtonStyle.danger, row=0)
            reinstall_button.callback = lambda inter: self.action_callback(inter, 'reinstall')
            self.add_item(reinstall_button)
        start_button = discord.ui.Button(label="▶ Start", style=discord.ButtonStyle.success, row=0)
        start_button.callback = lambda inter: self.action_callback(inter, 'start')
        stop_button = discord.ui.Button(label="⏸ Stop", style=discord.ButtonStyle.secondary, row=0)
        stop_button.callback = lambda inter: self.action_callback(inter, 'stop')
        restart_button = discord.ui.Button(label="🔁 Restart", style=discord.ButtonStyle.primary, row=0)
        restart_button.callback = lambda inter: self.action_callback(inter, 'restart')
        stats_button = discord.ui.Button(label="📊 Stats", style=discord.ButtonStyle.secondary, row=0)
        stats_button.callback = lambda inter: self.action_callback(inter, 'stats')

        password_button = discord.ui.Button(label="🔑 Password", style=discord.ButtonStyle.primary, row=1)
        password_button.callback = lambda inter: self.action_callback(inter, 'password')

        ssh_button = discord.ui.Button(label="🔐 SSH", style=discord.ButtonStyle.primary, row=2)
        ssh_button.callback = lambda inter: self.action_callback(inter, 'tmate')
        sshx_button = discord.ui.Button(label="🌐 SSHX", style=discord.ButtonStyle.primary, row=2)
        sshx_button.callback = lambda inter: self.action_callback(inter, 'sshx')
        tunnel_button = discord.ui.Button(label="🔄 Tunnel", style=discord.ButtonStyle.primary, row=2)
        tunnel_button.callback = lambda inter: self.action_callback(inter, 'reconnect_tunnel')

        ai_button = discord.ui.Button(label="🩺 AI Health", style=discord.ButtonStyle.success, row=3)
        ai_button.callback = lambda inter: self.action_callback(inter, 'ai_check')
        delete_button = discord.ui.Button(label="🗑️ Delete VPS", style=discord.ButtonStyle.danger, row=3)
        delete_button.callback = lambda inter: self.action_callback(inter, 'delete')
        refresh_button = discord.ui.Button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=3)
        refresh_button.callback = lambda inter: self.action_callback(inter, 'refresh')

        for item in (start_button, stop_button, restart_button, stats_button,
                     password_button, ssh_button, sshx_button, tunnel_button,
                     ai_button, delete_button, refresh_button):
            self.add_item(item)

    async def select_vps(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id and not self.is_admin:
            await interaction.response.send_message(
                embed=create_error_embed("Access Denied", "This is not your VPS!"), ephemeral=True)
            return
        self.selected_index = int(self.select.values[0])
        self._embed_cache = None   # ← invalidate cache so new embed is built
        await interaction.response.defer()
        new_embed = await self.create_vps_embed(self.selected_index)
        self.clear_items()
        self.add_action_buttons()
        await interaction.edit_original_response(embed=new_embed, view=self)

    async def action_callback(self, interaction: discord.Interaction, action: str):
        # Defer immediately to prevent interaction timeout (3-second window)
        try:
            await interaction.response.defer(ephemeral=True)
        except:
            # Already responded or interaction expired
            return
        
        if str(interaction.user.id) != self.user_id and not self.is_admin:
            await interaction.followup.send(embed=create_error_embed("Access Denied", "This is not your VPS!"), ephemeral=True)
            return
        if self.selected_index is None:
            await interaction.followup.send(embed=create_error_embed("No VPS Selected", "Please select a VPS first."), ephemeral=True)
            return
        actual_idx = self.actual_index if self.is_shared else self.indices[self.selected_index]
        target_vps = vps_data[self.owner_id][actual_idx]
        suspended = target_vps.get('suspended', False)
        if suspended and not self.is_admin and action not in {'stats', 'delete'}:
            await interaction.followup.send(embed=create_error_embed("Access Denied", "This VPS is suspended. Contact an admin to unsuspend."), ephemeral=True)
            return
        container_name = target_vps["container_name"]
        node_id = target_vps['node_id']
        # Guest-dependent buttons should be self-healing: if the DB says running
        # but the real LXC/KVM is stopped, reconcile it and start it before exec.
        # Power controls and snapshots intentionally remain explicit.
        guest_actions = {'password', 'tmate', 'sshx', 'reconnect_tunnel'}
        if action in guest_actions:
            try:
                state_result = await _ensure_vps_running_for_action(target_vps, action)
                if state_result.get('started'):
                    save_vps_data_immediate()
            except Exception as exc:
                await interaction.followup.send(
                    embed=create_error_embed('VPS Not Running', safe_error_summary(f'Prepare VPS for {action}', exc)),
                    ephemeral=True
                )
                return
        if action == 'refresh':
            try:
                self._embed_cache = None
                new_embed = await self.create_vps_embed(self.selected_index)
                await interaction.followup.send(embed=new_embed, ephemeral=True)
            except Exception as exc:
                await interaction.followup.send(embed=create_error_embed('Refresh Failed', str(exc)[:1500]), ephemeral=True)
            return

        if action == 'restart':
            if suspended and not self.is_admin:
                await interaction.followup.send(embed=create_error_embed('Access Denied', 'This VPS is suspended.'), ephemeral=True)
                return
            try:
                current = str(target_vps.get('status', 'stopped')).lower()
                result = await _panel_power_action(target_vps, 'restart' if current == 'running' else 'start')
                target_vps['status'] = 'running'
                if self.is_admin and suspended:
                    target_vps['suspended'] = False
                save_vps_data_immediate()
                self._embed_cache = None
                await interaction.followup.send(embed=create_success_embed('🔁 VPS Restarted', f'`{container_name}` is running again.'), ephemeral=True)
            except Exception as exc:
                await interaction.followup.send(embed=create_error_embed('Restart Failed', str(exc)[:1800]), ephemeral=True)
            return

        if action == 'password':
            try:
                password = target_vps.get('root_password')
                if not password:
                    password = generate_strong_password(20)
                    if str(target_vps.get('backend', 'lxc')).lower() == 'kvm':
                        await configure_kvm_guest_ssh(container_name, password=password)
                    else:
                        ok, detail = await configure_ssh(container_name, node_id, password)
                        if not ok:
                            raise RuntimeError(str(detail))
                    target_vps['root_password'] = password
                    save_vps_data_immediate()
                pass_embed = create_success_embed('🔑 VPS Password', f'Root credentials for `{container_name}`')
                add_field(pass_embed, 'Username', '`root`', True)
                add_field(pass_embed, 'Password', f'`{password}`', True)
                add_field(pass_embed, 'Security', 'Keep this private. The password is sent only to you.', False)
                try:
                    await interaction.user.send(embed=pass_embed)
                    await interaction.followup.send(embed=create_success_embed('🔐 Password Sent', 'The VPS password was sent to your DM.'), ephemeral=True)
                except discord.Forbidden:
                    await interaction.followup.send(embed=pass_embed, ephemeral=True)
            except Exception as exc:
                await interaction.followup.send(embed=create_error_embed('Password Failed', str(exc)[:1800]), ephemeral=True)
            return

        if action == 'delete':
            if self.is_shared:
                await interaction.followup.send(embed=create_error_embed('Access Denied', 'Shared VPS cannot be deleted from this panel.'), ephemeral=True)
                return
            if not self.is_admin and str(self.owner_id) != str(interaction.user.id):
                await interaction.followup.send(embed=create_error_embed('Access Denied', 'Only the VPS owner or an admin can delete this VPS.'), ephemeral=True)
                return
            class PanelDeleteConfirm(discord.ui.View):
                def __init__(self, parent):
                    super().__init__(timeout=60)
                    self.parent = parent
                @discord.ui.button(label='🗑️ Confirm Delete', style=discord.ButtonStyle.danger)
                async def confirm(self, inter: discord.Interaction, button: discord.ui.Button):
                    if str(inter.user.id) != str(self.parent.user_id) and not self.parent.is_admin:
                        await inter.response.send_message(embed=create_error_embed('Access Denied', 'Only the requester/admin can confirm this deletion.'), ephemeral=True)
                        return
                    await inter.response.defer(ephemeral=True)
                    try:
                        msg = await _panel_delete_vps(self.parent.owner_id, actual_idx)
                        await inter.followup.send(embed=create_success_embed('🗑️ VPS Deleted', msg), ephemeral=True)
                        self.stop()
                    except Exception as exc:
                        await inter.followup.send(embed=create_error_embed('Delete Failed', str(exc)[:1800]), ephemeral=True)
                @discord.ui.button(label='❌ Cancel', style=discord.ButtonStyle.secondary)
                async def cancel(self, inter: discord.Interaction, button: discord.ui.Button):
                    await inter.response.send_message(embed=create_info_embed('Deletion Cancelled', 'No changes were made.'), ephemeral=True)
                    self.stop()
            warning = create_warning_embed('⚠️ Delete VPS', f'This permanently removes `{container_name}` and its stored VPS record.\n\n**This cannot be undone.**')
            await interaction.followup.send(embed=warning, view=PanelDeleteConfirm(self), ephemeral=True)
            return

        if action == 'stats':
            try:
                stats = await get_container_stats(container_name, node_id)
                stats_embed = create_info_embed("📈 Live Statistics", f"Real-time stats for `{container_name}`")
                add_field(stats_embed, "Status", f"`{stats['status'].upper()}`", True)
                add_field(stats_embed, "CPU", f"{stats['cpu']:.1f}%", True)
                add_field(stats_embed, "Memory", f"{stats['ram']['used']}/{stats['ram']['total']} MB ({stats['ram']['pct']:.1f}%)", True)
                add_field(stats_embed, "Disk", stats['disk'], True)
                add_field(stats_embed, "Uptime", stats['uptime'], True)
                await interaction.followup.send(embed=stats_embed, ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("Stats Failed", str(e)), ephemeral=True)
            return
        if action == 'reinstall':
            if self.is_shared or self.is_admin:
                await interaction.followup.send(embed=create_error_embed("Access Denied", "Only the VPS owner can reinstall!"), ephemeral=True)
                return
            if suspended:
                await interaction.followup.send(embed=create_error_embed("Cannot Reinstall", "Unsuspend the VPS first."), ephemeral=True)
                return
            ram_gb = int(target_vps['ram'].replace('GB', ''))
            cpu = int(target_vps['cpu'])
            storage_gb = int(target_vps['storage'].replace('GB', ''))
            confirm_embed = create_warning_embed("Reinstall Warning",
                f"⚠️ **WARNING:** This will erase all data on VPS `{container_name}` and reinstall a fresh OS.\n\n"
                f"This action cannot be undone. Continue?")
            class ConfirmView(discord.ui.View):
                def __init__(self, parent_view, container_name, owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id):
                    super().__init__(timeout=60)
                    self.parent_view = parent_view
                    self.container_name = container_name
                    self.owner_id = owner_id
                    self.actual_idx = actual_idx
                    self.ram_gb = ram_gb
                    self.cpu = cpu
                    self.storage_gb = storage_gb
                    self.node_id = node_id

                @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
                async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
                    await inter.response.defer(ephemeral=True)
                    try:
                        # Keep the existing VPS intact until the user selects a valid OS.
                        # The selected image is validated before deletion in ReinstallOSSelectView.
                        os_view = ReinstallOSSelectView(self.parent_view, self.container_name, self.owner_id, self.actual_idx, self.ram_gb, self.cpu, self.storage_gb, self.node_id)
                        await inter.followup.send(embed=create_info_embed("Select OS", "Choose the new OS for reinstallation."), view=os_view, ephemeral=True)
                    except Exception as e:
                        await inter.followup.send(embed=create_error_embed("Delete Failed", f"Error: {str(e)}"), ephemeral=True)

                @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
                async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
                    new_embed = await self.parent_view.create_vps_embed(self.parent_view.selected_index)
                    await inter.response.edit_message(embed=new_embed, view=self.parent_view)

            await interaction.followup.send(embed=confirm_embed, view=ConfirmView(self, container_name, self.owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id), ephemeral=True)
            return
        
        suspended = target_vps.get('suspended', False)
        if action == 'start':
            try:
                current_status = str(target_vps.get('status', 'stopped')).lower()
                if current_status == 'running':
                    # KVM can be running in reality even if the DB is stale.
                    if str(target_vps.get('backend','lxc')).lower() == 'kvm':
                        state = await _run_local_process(['virsh','dominfo',container_name], timeout=15, check=False)
                        if re.search(r'^State:\s*running', state, re.I|re.M):
                            target_vps['status']='running'; save_vps_data_immediate()
                            await interaction.followup.send(embed=create_info_embed('Already Running', f'VPS `{container_name}` is already running.'), ephemeral=True)
                            return
                    else:
                        await interaction.followup.send(embed=create_info_embed('Already Running', f'VPS `{container_name}` is already running.'), ephemeral=True)
                        return
                result = await _panel_power_action(target_vps, 'start')
                target_vps['status'] = 'running'
                if self.is_admin and suspended:
                    target_vps['suspended'] = False
                save_vps_data_immediate()
                await interaction.followup.send(embed=create_success_embed('VPS Started', f'`{container_name}` is now running.\n\n{result}'), ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed('Start Failed', str(e)[:1800]), ephemeral=True)
        elif action == 'stop':
            try:
                result = await _panel_power_action(target_vps, 'stop')
                target_vps['status'] = 'stopped'
                save_vps_data_immediate()
                await interaction.followup.send(embed=create_success_embed('VPS Stopped', f'`{container_name}` shutdown requested.\n\n{result}'), ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed('Stop Failed', str(e)[:1800]), ephemeral=True)
        elif action == 'tmate':
            if suspended:
                await interaction.followup.send(embed=create_error_embed("Access Denied", "Cannot access suspended VPS."), ephemeral=True)
                return
            if str(target_vps.get('status', 'stopped')).lower() != 'running':
                try:
                    if str(target_vps.get('backend', 'lxc')).lower() == 'kvm':
                        state = await _run_local_process(['virsh', 'domstate', container_name], timeout=8, check=False)
                        running_now = 'running' in str(state).lower()
                    else:
                        info = await execute_lxc(container_name, f'info {container_name}', node_id=node_id, timeout=8)
                        running_now = bool(re.search(r'(?im)^Status:\s*Running\s*$', str(info)))
                except Exception:
                    running_now = False
                if not running_now:
                    await interaction.followup.send(embed=create_error_embed("VPS Not Running", "The VPS is stopped or still booting. Start it, wait 10–30 seconds, then retry SSH."), ephemeral=True)
                    return
                target_vps['status'] = 'running'
                save_vps_data_immediate()
            try:
                await interaction.followup.send(embed=create_info_embed("🔐 SSH Manager", "Preparing secure SSH access…"), ephemeral=True)
                cn = container_name
                if target_vps.get('backend', 'lxc') == 'kvm':
                    networks = await wait_for_kvm_network(cn, timeout=20)
                    ip = next(iter(networks.values()), None)
                    if not ip:
                        await kvm_guest_network_doctor(cn, repair=True)
                        networks = await wait_for_kvm_network(cn, timeout=20)
                        ip = next(iter(networks.values()), None)
                    if not ip:
                        raise RuntimeError("KVM guest has no usable IPv4 lease. Run `!kvm-network-repair` and try again.")
                    await interaction.followup.send(embed=create_info_embed("🔐 SSH Manager", "Creating secure public SSH access for the KVM VPS…"), ephemeral=True)
                    # Always validate/reuse the real KVM guest-side tunnel.
                    # Do not trust a stale DB endpoint: after a tunnel dies/reconnects
                    # Pinggy may assign a different host/port. kvm_guest_pinggy_tunnel()
                    # checks the guest tunnel process and creates a new one when needed.
                    pinggy_host, pinggy_port = await kvm_guest_pinggy_tunnel(cn, timeout=45)
                    target_vps['pinggy_host'] = str(pinggy_host)
                    target_vps['pinggy_port'] = str(pinggy_port)
                    target_vps['pinggy_provider'] = 'pinggy-kvm'
                    save_vps_data_immediate()
                    ssh_embed = create_embed("🔐 SSH Access Ready", f"Public SSH access for KVM VPS `{cn}`", 0x00ff88)
                    add_field(ssh_embed, "Command", f"`ssh root@{pinggy_host} -p {pinggy_port}`", False)
                    add_field(ssh_embed, "Host", f"`{pinggy_host}`", True)
                    add_field(ssh_embed, "Port", f"`{pinggy_port}`", True)
                    add_field(ssh_embed, "Username", "`root`", True)
                    add_field(ssh_embed, "Password", f"`{target_vps.get('root_password', 'Check VPS credentials')}`", False)
                    add_field(ssh_embed, "Network", f"Guest IPv4 `{ip}` via Pinggy TCP tunnel", False)
                    add_field(ssh_embed, "Security", "The Pinggy endpoint is temporary and may change after reconnect.", False)
                    try:
                        await interaction.user.send(embed=ssh_embed)
                        await interaction.followup.send(embed=create_success_embed("✅ SSH Ready", "KVM SSH connection details were sent to your DM."), ephemeral=True)
                    except discord.Forbidden:
                        await interaction.followup.send(embed=ssh_embed, ephemeral=True)
                    return

                password = target_vps.get('root_password') or generate_strong_password(20)
                ssh_ok, ssh_detail = await configure_ssh(cn, node_id, password)
                if not ssh_ok:
                    await interaction.followup.send(embed=create_error_embed("SSH Setup Failed", str(ssh_detail)[:1600]), ephemeral=True)
                    return

                # Prefer an existing tunnel; otherwise create a fresh Pinggy TCP tunnel.
                pinggy_host = target_vps.get('pinggy_host')
                pinggy_port = target_vps.get('pinggy_port')
                if not pinggy_host or not pinggy_port:
                    pinggy_raw = await start_pinggy_tunnel(cn, node_id)
                    pinggy_host, pinggy_port = parse_pinggy_url(pinggy_raw) if pinggy_raw else (None, None)
                    if pinggy_host and pinggy_port:
                        target_vps['pinggy_host'] = pinggy_host
                        target_vps['pinggy_port'] = pinggy_port
                        save_vps_data_immediate()

                if not pinggy_host or not pinggy_port:
                    networks = await get_container_networks(cn, node_id)
                    ips = [ip for ip in networks.values() if ip and not ip.startswith('127.')]
                    if not ips:
                        raise RuntimeError("SSH is installed, but no reachable VPS IP/tunnel was found. Try Reconnect Tunnel or check VPS networking.")
                    ssh_embed = create_embed("🔐 SSH Access", f"SSH is configured for `{cn}`", 0x00ff88)
                    add_field(ssh_embed, "Internal SSH", f"`ssh root@{ips[0]}`", False)
                    add_field(ssh_embed, "Username", "`root`", True)
                    add_field(ssh_embed, "Password", f"`{password}`", True)
                    add_field(ssh_embed, "Note", "The IP may only be reachable from the VPS network.", False)
                else:
                    ssh_embed = create_embed("🔐 SSH Access Ready", f"Secure SSH access for `{cn}`", 0x00ff88)
                    add_field(ssh_embed, "Command", f"`ssh root@{pinggy_host} -p {pinggy_port}`", False)
                    add_field(ssh_embed, "Host", f"`{pinggy_host}`", True)
                    add_field(ssh_embed, "Port", f"`{pinggy_port}`", True)
                    add_field(ssh_embed, "Username", "`root`", True)
                    add_field(ssh_embed, "Password", f"`{password}`", True)
                    add_field(ssh_embed, "Security", "Never share these credentials or the tunnel endpoint.", False)
                try:
                    await interaction.user.send(embed=ssh_embed)
                    await interaction.followup.send(embed=create_success_embed("✅ SSH Ready", "SSH credentials and connection details were sent to your DM."), ephemeral=True)
                except discord.Forbidden:
                    await interaction.followup.send(embed=ssh_embed, ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("SSH Failed", str(e)[:1800]), ephemeral=True)

        elif action == 'sshx':
            if suspended:
                await interaction.followup.send(embed=create_error_embed("Access Denied", "Cannot access suspended VPS."), ephemeral=True)
                return
            try:
                # Always verify actual state; the DB may lag behind LXD.
                backend_now = str(target_vps.get('backend', 'lxc')).lower()
                actually_running = False
                try:
                    if backend_now == 'kvm':
                        state = await _run_local_process(['virsh', 'domstate', container_name], timeout=8, check=False)
                        actually_running = str(state).strip().lower() == 'running'
                    else:
                        actually_running = await _guest_is_running(container_name, node_id)
                except Exception:
                    actually_running = False
                if not actually_running:
                    target_vps['status'] = 'stopped'
                    save_vps_data_immediate()
                    await interaction.followup.send(embed=create_error_embed("VPS Not Running", "The VPS is stopped or still booting. Start it, wait 10–30 seconds, then retry SSHX."), ephemeral=True)
                    return
                if str(target_vps.get('status', '')).lower() != 'running':
                    target_vps['status'] = 'running'
                    save_vps_data_immediate()
                await interaction.followup.send(embed=create_info_embed("🌐 SSHX", "Generating SSHX link… please wait ~6 seconds."), ephemeral=True)

                cn = container_name
                node = get_node(node_id)
                if target_vps.get('backend', 'lxc') == 'kvm':
                    networks = await wait_for_kvm_network(cn, timeout=60)
                    ip = next(iter(networks.values()), None)
                    if not ip:
                        doctor = await kvm_guest_network_doctor(cn, repair=True)
                        networks = await wait_for_kvm_network(cn, timeout=30)
                        ip = next(iter(networks.values()), None)
                        if not ip:
                            detail = doctor.get('error') or doctor.get('raw') or 'No DHCPv4 lease was detected.'
                            await interaction.followup.send(embed=create_error_embed("KVM Network Not Ready", f"The VPS has not received an IPv4 DHCP lease yet. QEMU Guest Agent is not required for this check.\n```text\n{str(detail)[-1400:]}\n```"), ephemeral=True)
                            return
                    if not await wait_for_kvm_guest_agent(cn, timeout=45):
                        await interaction.followup.send(embed=create_error_embed("KVM Guest Agent Not Ready", f"IPv4 is available (`{ip}`), but QEMU Guest Agent is still offline. SSHX will be retried after the guest finishes booting."), ephemeral=True)
                        return
                    try:
                        await interaction.followup.send(embed=create_info_embed("🌐 SSHX", "Checking guest IPv4 and generating a secure SSHX link…"), ephemeral=True)
                        sshx_link = await kvm_guest_sshx_link(cn, timeout=25)
                        ssh_embed = create_embed("🌐 SSHX Link", f"SSHX web terminal for KVM VPS `{cn}`", 0x7289da)
                        add_field(ssh_embed, "🔗 Link", f"`{sshx_link}`", False)
                        add_field(ssh_embed, "IPv4", f"`{ip}`", True)
                        add_field(ssh_embed, "⚠️ Security", "This link gives terminal access. Do not share it.", False)
                        try:
                            await interaction.user.send(embed=ssh_embed)
                            await interaction.followup.send(embed=create_success_embed("✅ SSHX Sent", "KVM SSHX link was sent to your DM."), ephemeral=True)
                        except discord.Forbidden:
                            await interaction.followup.send(embed=ssh_embed, ephemeral=True)
                    except Exception as sshx_exc:
                        ssh_embed = create_embed("🌐 KVM SSH Fallback", f"SSHX could not be started for `{cn}`, but IPv4/SSH is available.", 0x7289da)
                        add_field(ssh_embed, "SSH Command", f"`ssh root@{ip}`", False)
                        add_field(ssh_embed, "Password", f"`{target_vps.get('root_password', 'Check VPS credentials')}`", False)
                        add_field(ssh_embed, "IPv4", f"`{ip}`", True)
                        add_field(ssh_embed, "SSHX Diagnostic", f"`{str(sshx_exc)[:900]}`", False)
                        try:
                            await interaction.user.send(embed=ssh_embed)
                            await interaction.followup.send(embed=create_error_embed("⚠️ SSHX Unavailable", "Direct SSH details were sent to your DM as a fallback."), ephemeral=True)
                        except discord.Forbidden:
                            await interaction.followup.send(embed=ssh_embed, ephemeral=True)
                    return
                async def shell(cmd: str, timeout: int = 120) -> tuple:
                    # Route LXC guest commands through execute_lxc so non-default
                    # projects are resolved consistently and instance errors surface.
                    try:
                        argv = shlex.split(cmd)
                        if (argv and argv[0] == LXC_CMD and len(argv) >= 5
                                and argv[1] == 'exec' and argv[2] == cn and '--' in argv):
                            sep = argv.index('--')
                            guest_argv = argv[sep + 1:]
                            if not guest_argv:
                                return '', 'Empty guest command', 2
                            result = await execute_lxc(
                                cn, f"exec {cn} -- {shlex.join(guest_argv)}",
                                node_id=node_id, timeout=timeout
                            )
                            return (result if isinstance(result, str) else ''), '', 0
                    except asyncio.TimeoutError as exc:
                        return '', str(exc), 124
                    except Exception as exc:
                        return '', str(exc), 1
                    proc = await asyncio.create_subprocess_shell(
                        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )
                    try:
                        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                            await proc.wait()
                        except Exception:
                            pass
                        return '', f'Command timed out after {timeout}s', 124
                    return (out or b'').decode(errors='ignore'), (err or b'').decode(errors='ignore'), proc.returncode

                def extract_sshx_link(text: str) -> str:
                    for line in text.splitlines():
                        for part in line.split():
                            if "sshx.io/s/" in part:
                                return part.strip().rstrip(".,;")
                    return ""

                if node and node['is_local']:
                    # Step 1: Check if sshx already installed
                    check_out, _, check_rc = await shell(
                        f"{LXC_CMD} exec {cn} -- bash -c 'command -v sshx || ls /root/.local/bin/sshx 2>/dev/null || ls /usr/local/bin/sshx 2>/dev/null'",
                        timeout=10
                    )
                    sshx_bin = check_out.strip().splitlines()[0].strip() if check_out.strip() else ""

                    if not sshx_bin:
                        # Install SSHX plus the PTY tooling it needs. SSHX is a real
                        # interactive terminal, so a plain background process without
                        # a pseudo-terminal can generate a link but leave the web
                        # terminal unusable or make link discovery race the startup.
                        install_script = r"""
set -eu
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y >/dev/null 2>&1 || true
  apt-get install -y curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v apk >/dev/null 2>&1; then
  apk add --no-cache curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then
  yum install -y curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v zypper >/dev/null 2>&1; then
  zypper --non-interactive install curl ca-certificates util-linux bash >/dev/null 2>&1 || true
fi
curl -sSf https://sshx.io/get | sh
"""
                        out_i, err_i, rc = await shell(
                            f"{LXC_CMD} exec {cn} -- bash -lc {shlex.quote(install_script)}",
                            timeout=120
                        )

                        if rc != 0 and "sshx" not in (out_i + err_i).lower():
                            logger.warning(f"SSHX install may have failed for {cn}: rc={rc} err={err_i[:500]}")
                        # Re-check path after install
                        check_out2, _, _ = await shell(
                            f"{LXC_CMD} exec {cn} -- bash -c 'command -v sshx || ls /root/.local/bin/sshx 2>/dev/null || ls /usr/local/bin/sshx 2>/dev/null'",
                            timeout=10
                        )
                        sshx_bin = check_out2.strip().splitlines()[0].strip() if check_out2.strip() else "sshx"

                    # Step 2: Read an existing SSHX link.
                    # Do not spawn a foreground sshx subprocess here: the old code
                    # left a BaseSubprocessTransport alive when the Discord event
                    # loop closed, producing `RuntimeError: Event loop is closed`.
                    # Step 2: First try to grab existing sshx link from state file
                    sshx_link = ""
                    grep_out, _, _ = await shell(
                        f"{LXC_CMD} exec {cn} -- bash -c "
                        f"'grep -aho \"https://sshx.io/s/[A-Za-z0-9#=_-]*\" /root/.sshx/* 2>/dev/null | head -n1'",
                        timeout=5
                    )
                    sshx_link = extract_sshx_link(grep_out)

                    if not sshx_link:
                        # Start sshx in background and wait for state file
                        # IMPORTANT: start SSHX through `script` so the guest shell gets a real PTY.
                        # Without a PTY, non-interactive commands such as `bash <(curl ...)` may run,
                        # but installers that ask for numeric input (1/2/3/4), passwords, confirmations,
                        # arrow keys, Ctrl+C, etc. can appear frozen because stdin is not a terminal.
                        # Keep SSHX detached from the bot process, but give it a dedicated PTY.
                        # Launch SSHX with a persistent, detached PTY. `setsid`
                        # prevents the LXC exec session from taking the terminal
                        # down when the bot command returns. `script` gives SSHX a
                        # real PTY, which is required for interactive shell input.
                        launch_script = f"""
set -eu
SSHX_BIN={shlex.quote(sshx_bin)}
if [ -f /tmp/sshx.pid ]; then kill "$(cat /tmp/sshx.pid)" >/dev/null 2>&1 || true; fi
rm -f /tmp/sshx.log /tmp/sshx.pid
if [ -s /tmp/sshx.pid ]; then kill "$(cat /tmp/sshx.pid)" >/dev/null 2>&1 || true; fi; rm -f /tmp/sshx.pid
command -v setsid >/dev/null 2>&1 || {{ echo 'SSHX_ERROR=setsid_not_installed'; exit 21; }}
nohup setsid \"$SSHX_BIN\" </dev/null >/tmp/sshx.log 2>&1 &
echo $! >/tmp/sshx.pid
"""
                        await shell(
                            f"{LXC_CMD} exec {cn} -- bash -lc {shlex.quote(launch_script)}",
                            timeout=15
                        )
                        # SSHX can take a few seconds to establish its session.
                        # Search both the live log and the typescript transcript.
                        for _ in range(15):
                            await asyncio.sleep(1)
                            grep_out2, _, _ = await shell(
                                f"{LXC_CMD} exec {cn} -- bash -lc "
                                f"'grep -ahoE \"https://sshx\\.io/s/[A-Za-z0-9#=_-]+\" /tmp/sshx.log 2>/dev/null | head -n1'",
                                timeout=5
                            )
                            sshx_link = extract_sshx_link(grep_out2)
                            if sshx_link:
                                break
                else:
                    # Remote node
                    try:
                        await execute_lxc(
                            cn,
                            f"exec {cn} -- bash -c 'command -v sshx || (apt-get install -y curl 2>/dev/null; curl -sSf https://sshx.io/get | sh)'",
                            node_id=node_id, timeout=90
                        )
                    except Exception:
                        pass
                    try:
                        # Remote nodes get the same detached PTY-backed process as
                        # local nodes. Keep the launcher distro-friendly; if the
                        # node is Debian/Ubuntu, install the small PTY dependency.
                        remote_launch = """
set -eu
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y >/dev/null 2>&1 || true
  apt-get install -y curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v apk >/dev/null 2>&1; then
  apk add --no-cache curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then
  yum install -y curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v zypper >/dev/null 2>&1; then
  zypper --non-interactive install curl ca-certificates util-linux bash >/dev/null 2>&1 || true
fi
command -v sshx >/dev/null 2>&1 || (curl -sSf https://sshx.io/get | sh)
SSHX_BIN=\"$(command -v sshx || printf '%s' /root/.local/bin/sshx)\"
if [ -f /tmp/sshx.pid ]; then kill "$(cat /tmp/sshx.pid)" >/dev/null 2>&1 || true; fi
rm -f /tmp/sshx.log /tmp/sshx.pid
if [ -s /tmp/sshx.pid ]; then kill "$(cat /tmp/sshx.pid)" >/dev/null 2>&1 || true; fi; rm -f /tmp/sshx.pid
command -v setsid >/dev/null 2>&1 || exit 21
nohup setsid \"$SSHX_BIN\" </dev/null >/tmp/sshx.log 2>&1 &
echo $! >/tmp/sshx.pid
"""
                        await execute_lxc(
                            cn,
                            f"exec {cn} -- bash -lc {shlex.quote(remote_launch)}",
                            node_id=node_id, timeout=120
                        )
                        for _ in range(15):
                            await asyncio.sleep(1)
                            raw = await execute_lxc(
                                cn,
                                f"exec {cn} -- bash -lc 'grep -ahoE \"https://sshx\\.io/s/[A-Za-z0-9#=_-]+\" /tmp/sshx.log 2>/dev/null | head -n1'",
                                node_id=node_id, timeout=5
                            )
                            sshx_link = extract_sshx_link(raw if isinstance(raw, str) else "")
                            if sshx_link:
                                break
                    except Exception as sshx_remote_exc:
                        logger.warning(f"Remote SSHX launch failed for {cn}: {sshx_remote_exc}")
                        sshx_link = ""
                    if not sshx_link:
                        try:
                            raw2 = await execute_lxc(
                                cn,
                                f"exec {cn} -- bash -c "
                                f"'grep -aho \"https://sshx.io/s/[A-Za-z0-9#=_-]*\" /root/.sshx/* 2>/dev/null | head -n1'",
                                node_id=node_id, timeout=10
                            )
                            sshx_link = extract_sshx_link(raw2 if isinstance(raw2, str) else "")
                        except Exception:
                            pass

                if sshx_link:
                    try:
                        sshx_embed = create_embed("🌐 SSHX Link", f"SSHX web terminal for VPS `{cn}`:", 0x7289da)
                        add_field(sshx_embed, "🔗 Link", f"`{sshx_link}`", False)
                        add_field(sshx_embed, "⚠️ Note", "This link gives full terminal access. Do not share it.", False)
                        await interaction.user.send(embed=sshx_embed)
                        await interaction.followup.send(embed=create_success_embed("✅ SSHX Sent", "Check your DMs for the SSHX link!"), ephemeral=True)
                    except discord.Forbidden:
                        await interaction.followup.send(embed=create_error_embed("DM Failed", "Enable DMs to receive the SSHX link!"), ephemeral=True)
                else:
                    # Do not incorrectly blame internet connectivity: Pinggy may be working
                    # while SSHX itself failed to start. Expose the real diagnostic and
                    # provide the already-working SSH tunnel path when available.
                    diagnostic = "SSHX process did not publish a web link. Check the VPS SSHX log/PTY setup and try again."
                    try:
                        diag = await execute_lxc(cn, f"exec {cn} -- bash -lc 'tail -n 30 /tmp/sshx.log 2>/dev/null || true'", node_id=node_id, timeout=8)
                        if diag:
                            diagnostic += f"\n\nLast SSHX output:\n```text\n{diag[-1800:]}\n```"
                    except Exception:
                        pass
                    pinggy_host = target_vps.get('pinggy_host')
                    pinggy_port = target_vps.get('pinggy_port')
                    if not pinggy_host or not pinggy_port:
                        try:
                            pinggy_raw = await asyncio.wait_for(start_pinggy_tunnel(cn, node_id), timeout=45)
                            pinggy_host, pinggy_port = parse_pinggy_url(pinggy_raw) if pinggy_raw else (None, None)
                            if pinggy_host and pinggy_port:
                                target_vps['pinggy_host'] = pinggy_host
                                target_vps['pinggy_port'] = pinggy_port
                                save_vps_data_immediate()
                        except Exception as pinggy_exc:
                            logger.warning('Automatic Pinggy fallback failed for %s: %s', cn, pinggy_exc)
                    if pinggy_host and pinggy_port:
                        diagnostic += f"\n\n✅ **SSH fallback is available:** `ssh root@{pinggy_host} -p {pinggy_port}`"
                    await interaction.followup.send(embed=create_error_embed("SSHX Failed", diagnostic), ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("SSHX Error", str(e)), ephemeral=True)
                return
            
        elif action == 'ai_check':
            if suspended:
                await interaction.followup.send(embed=create_warning_embed("🩺 AI Health", "This VPS is suspended; automatic repair is paused."), ephemeral=True)
                return
            try:
                await interaction.followup.send(embed=create_info_embed("🩺 VoxAI Health", "Running VPS diagnostics and applying safe repairs if required…"), ephemeral=True)
                result = await _ai_repair_vps(self.owner_id, target_vps, force=True)
                if result.get('status') in ('healthy','repaired'):
                    actions = "\n".join(f"• {a}" for a in (result.get('actions') or ["No repair was necessary."]))
                    await interaction.followup.send(embed=create_success_embed("🩺 VPS Healthy", actions), ephemeral=True)
                else:
                    detail = result.get('detail') or result.get('status') or 'Unknown issue'
                    await interaction.followup.send(embed=create_error_embed("🩺 AI Repair Incomplete", f"{detail[-1600:]}"), ephemeral=True)
            except Exception as exc:
                await interaction.followup.send(embed=create_error_embed("🩺 AI Health Failed", str(exc)[:1800]), ephemeral=True)

        elif action == 'reconnect_tunnel':
            target_vps = vps_data[self.owner_id][actual_idx]
            container_name = target_vps['container_name']
            node_id = target_vps['node_id']
            backend = str(target_vps.get('backend', 'lxc')).lower()
            suspended = target_vps.get('suspended', False)
            if suspended:
                await interaction.followup.send(
                    embed=create_error_embed("Access Denied", "Cannot start tunnel on a suspended VPS."),
                    ephemeral=True)
                return
            current_status = target_vps.get('status', 'stopped')
            if current_status != 'running':
                await interaction.followup.send(
                    embed=create_error_embed("VPS Not Running", "Please start the VPS first."),
                    ephemeral=True)
                return

            label = "KVM Pinggy TCP tunnel" if backend == 'kvm' else "Pinggy SSH tunnel"
            await interaction.followup.send(
                embed=create_info_embed("🔄 Reconnecting Tunnel", f"Reconnecting {label}, please wait..."),
                ephemeral=True)
            try:
                # IMPORTANT: KVM guests are not LXC containers. The old code called
                # start_pinggy_tunnel() here for every backend, which executes the
                # tunnel through the LXC/Incus path and therefore fails on KVM.
                if backend == 'kvm':
                    networks = await wait_for_kvm_network(container_name, timeout=20)
                    ip = next(iter(networks.values()), None)
                    if not ip:
                        doctor = await kvm_guest_network_doctor(container_name, repair=True)
                        networks = await wait_for_kvm_network(container_name, timeout=25)
                        ip = next(iter(networks.values()), None)
                        if not ip:
                            detail = doctor.get('error') or doctor.get('raw') or 'No usable IPv4/DHCP lease was detected.'
                            raise RuntimeError(f"KVM guest networking is not ready.\n{str(detail)[-1200:]}")
                    pinggy_host, pinggy_port = await kvm_guest_pinggy_tunnel(container_name, timeout=45)
                    target_vps['pinggy_provider'] = 'pinggy-kvm'
                else:
                    pinggy_raw = await start_pinggy_tunnel(container_name, node_id)
                    pinggy_host, pinggy_port = parse_pinggy_url(pinggy_raw) if pinggy_raw else (None, None)
                    if not pinggy_host or not pinggy_port:
                        raise RuntimeError("Pinggy did not return a TCP endpoint. SSHX is working, so the VPS itself is reachable; Pinggy handshake or endpoint detection is failing. Try Reconnect Tunnel once and inspect the Pinggy log if it repeats.")
                    target_vps['pinggy_provider'] = 'pinggy-lxc'

                if not pinggy_host or not pinggy_port:
                    raise RuntimeError("Pinggy tunnel did not return a valid host/port.")

                target_vps['pinggy_host'] = str(pinggy_host)
                target_vps['pinggy_port'] = str(pinggy_port)
                pinggy_ips = await asyncio.to_thread(resolve_pinggy_ipv4, pinggy_host)
                target_vps['pinggy_ips'] = pinggy_ips
                save_vps_data_immediate()

                tunnel_embed = create_success_embed("✅ Tunnel Connected!", f"{label} is ready.")
                tunnel_embed.add_field(
                    name="🔐 SSH Command",
                    value=f"`ssh root@{pinggy_host} -p {pinggy_port}`",
                    inline=False)
                tunnel_embed.add_field(name="👤 Username", value="`root`", inline=True)
                tunnel_embed.add_field(
                    name="🌐 Pinggy Public IP",
                    value=("\n".join(f"`{ip}`" for ip in pinggy_ips[:5])
                           if pinggy_ips else "`DNS lookup unavailable`"),
                    inline=True)
                tunnel_embed.add_field(
                    name="🔑 Password",
                    value=f"`{target_vps.get('root_password', 'Check your VPS credentials')}`",
                    inline=True)
                if backend == 'kvm':
                    tunnel_embed.add_field(name="🌐 Guest IPv4", value=f"`{ip}`", inline=True)
                tunnel_embed.add_field(
                    name="ℹ️ Note",
                    value="The Pinggy endpoint can change when the tunnel is recreated.",
                    inline=False)
                try:
                    await interaction.user.send(embed=tunnel_embed)
                    await interaction.followup.send(
                        embed=create_success_embed("✅ Sent!", "SSH credentials and the new tunnel endpoint were sent to your DM."),
                        ephemeral=True)
                except discord.Forbidden:
                    await interaction.followup.send(embed=tunnel_embed, ephemeral=True)
            except Exception as e:
                await interaction.followup.send(
                    embed=create_error_embed("Tunnel Failed", str(e)[:1800]),
                    ephemeral=True)

@bot.command(name='tunnel-status', aliases=['ssh-tunnel-status'])
async def tunnel_status(ctx, vps_ref: str = None):
    """Show and repair the SSH/Pinggy state of a VPS owned by the caller or any VPS for admins."""
    try:
        if not vps_ref:
            owned = vps_data.get(str(ctx.author.id), [])
            if not owned:
                await ctx.send(embed=create_error_embed('No VPS', 'You do not have a VPS.'))
                return
            vps = owned[0]
        else:
            vps = resolve_vps_reference(vps_ref)
            if not vps:
                await ctx.send(embed=create_error_embed('VPS Not Found', 'Use the VPS ID or exact container name.'))
                return
            if not is_admin_user_id(str(ctx.author.id)) and str(vps.get('user_id')) != str(ctx.author.id):
                await ctx.send(embed=create_error_embed('Access Denied', 'You can only inspect your own VPS.'))
                return
        cn=str(vps.get('container_name')); nid=int(vps.get('node_id') or 1)
        backend=str(vps.get('backend','lxc')).lower()
        if backend == 'kvm':
            state='KVM'
            host=vps.get('pinggy_host'); port=vps.get('pinggy_port')
        else:
            state=await get_container_status_local(cn) if (get_node(nid) or {}).get('is_local') else 'remote'
            host=vps.get('pinggy_host'); port=vps.get('pinggy_port')
            alive=await _ai_tunnel_alive(vps)
            if not alive:
                host=port=None
        text=f"**VPS:** `{cn}`\n**State:** `{state}`\n**SSH:** `22`\n**Pinggy:** `{host}:{port}`" if host and port else f"**VPS:** `{cn}`\n**State:** `{state}`\n**SSH:** `22`\n**Pinggy:** `NOT CONNECTED`"
        await ctx.send(embed=create_info_embed('🔐 SSH / Tunnel Status', text))
    except Exception as exc:
        await ctx.send(embed=create_error_embed('Tunnel Status Failed', str(exc)[:1600]))


@bot.command(name='manage')
async def manage_vps(ctx, user: discord.Member = None):
    try:
        if user:
            if str(ctx.author.id) != str(MAIN_ADMIN_ID) and str(ctx.author.id) not in admin_data.get("admins", []):
                await ctx.send(embed=create_error_embed("Access Denied", "Only admins can manage other users' VPS."))
                return
            user_id = str(user.id)
            vps_list = vps_data.get(user_id, [])
            if not vps_list:
                await ctx.send(embed=create_error_embed("No VPS Found", f"{user.mention} doesn't have any {BOT_NAME} VPS."))
                return
            view = ManageView(str(ctx.author.id), vps_list, is_admin=True, owner_id=user_id)
            embed = await view.get_initial_embed()
            await ctx.send(embed=embed, view=view)
        else:
            user_id = str(ctx.author.id)
            vps_list = vps_data.get(user_id, [])
            if not vps_list:
                embed = create_error_embed("No VPS Found", f"You don't have any {BOT_NAME} VPS. Contact an admin to create one.")
                add_field(embed, "Quick Actions", f"• `{PREFIX}myvps` - List VPS\n• Contact admin for VPS creation", False)
                await ctx.send(embed=embed)
                return
            view = ManageView(user_id, vps_list)
            embed = await view.get_initial_embed()
            await ctx.send(embed=embed, view=view)
    except Exception as e:
        logger.error(f"manage command error: {e}")
        await ctx.send(embed=create_error_embed("Error", f"Failed to open VPS manager: {str(e)}"))

async def get_node_status(node_id: int) -> str:
    node = get_node(node_id)
    if not node:
        return "❓ Unknown"
    if node['is_local']:
        return "🟢 Online (Local)"
    # Remote nodes - check connectivity but don't spam errors
    try:
        response = await http_request('GET', f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
        if response.status_code == 200:
            return "🟢 Online"
        else:
            return "🔴 Offline (Network unreachable)"
    except requests.exceptions.ConnectionError:
        return "🔴 Unreachable (Network issue)"
    except requests.exceptions.Timeout:
        return "🔴 No response"
    except Exception:
        return "🔴 Offline"


def get_host_disk_usage():
    """Get host disk usage - cross-platform compatible"""
    try:
        import platform
        system = platform.system()
        
        if system == "Windows":
            # Windows: Use wmic or psutil
            try:
                import psutil
                disk = psutil.disk_usage('/')
                return f"{disk.used // (1024**3)} GB / {disk.total // (1024**3)} GB ({disk.percent}%)"
            except ImportError:
                # Fallback for Windows without psutil
                try:
                    result = subprocess.run(['wmic', 'LogicalDisk', 'get', 'Size,FreeSpace'], 
                                          capture_output=True, text=True, timeout=5)
                    lines = result.stdout.strip().split('\n')
                    if len(lines) > 1:
                        values = lines[1].split()
                        if len(values) >= 2:
                            size = int(values[0]) // (1024**3)
                            free = int(values[1]) // (1024**3)
                            used = size - free
                            percent = (used / size * 100) if size > 0 else 0
                            return f"{used} GB / {size} GB ({percent:.0f}%)"
                except:
                    pass
                return "Unknown"
        else:
            # Linux/Unix: Use df command
            result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=10)
            lines = result.stdout.splitlines()
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 5:
                    used = parts[2]
                    size = parts[1]
                    perc = parts[4]
                    return f"{used}/{size} ({perc})"
            return "Unknown"
    except Exception as e:
        logger.debug(f"Error getting disk usage: {e}")
        return "Unknown"


async def get_host_stats(node_id: int) -> Dict:
    node = get_node(node_id)
    if node['is_local']:
        return {
            "cpu": get_host_cpu_usage(),
            "ram": get_host_ram_usage(),
            "disk": get_host_disk_usage()
        }
    else:
        url = f"{node['url']}/api/get_host_stats"
        params = {"api_key": node["api_key"]}
        try:
            response = await http_request('GET', url, params=params, timeout=10)
            response.raise_for_status()
            stats = response.json()
            # Fallbacks if remote API doesn't provide
            stats['disk'] = stats.get('disk', 'Unknown')
            return stats
        except Exception as e:
            # Remote node unreachable - don't spam error logs
            logger.debug(f"Remote node {node['name']} stats unavailable: {type(e).__name__}")
            return {"cpu": 0.0, "ram": 0.0, "disk": "Unknown"}


@bot.command(name='vps-list')
@is_admin()
async def vps_list(ctx, node_id: int = 1):
    node = get_node(node_id)
    if not node:
        await ctx.send(embed=create_error_embed("Node Not Found", f"Node ID {node_id} not found."))
        return

    # Get node status
    status = await get_node_status(node_id)
    is_online = status.startswith("🟢")

    # Get node resource stats (will use defaults if offline)
    stats = await get_host_stats(node_id)
    cpu_usage = stats.get('cpu', 0.0)
    ram_usage = stats.get('ram', 0.0)
    disk_usage = stats.get('disk', 'Unknown')

    # Resources field text (modern: compact inline stats with progress-like emojis)
    if is_online:
        resources_text = (
            f"**CPU** {cpu_usage:.0f}% {'█' * int(cpu_usage / 5) + '░' * (20 - int(cpu_usage / 5))} "
            f"\n**RAM** {ram_usage:.0f}% {'█' * int(ram_usage / 5) + '░' * (20 - int(ram_usage / 5))} "
            f"\n**Disk** {disk_usage}"
        )
    else:
        resources_text = "⚠️ Resources unavailable (Offline)"

    # Get VPS capacity
    current_vps = get_current_vps_count(node_id)
    total_capacity = node['total_vps']
    capacity_percent = (current_vps / total_capacity * 100) if total_capacity > 0 else 0
    capacity_text = f"{current_vps}/{total_capacity} ({capacity_percent:.0f}%)"

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM vps WHERE node_id = ?', (node_id,))
    rows = cur.fetchall()
    conn.close()

    total_vps = len(rows)

    # Modern counters: use more intuitive emojis and clean layout
    running = 0
    stopped = 0
    suspended = 0
    other = 0
    vps_info = []
    for i, row in enumerate(rows, 1):
        vps = dict(row)
        user_id = vps['user_id']
        try:
            user = await bot.fetch_user(int(user_id))
            username = user.name
        except:
            username = f"Unknown ({user_id})"

        status = vps.get('status', 'unknown')
        suspended_flag = vps.get('suspended', False)

        # Count logic: suspended first, then status if not suspended
        if suspended_flag:
            suspended += 1
        elif status == 'running':
            running += 1
        elif status == 'stopped':
            stopped += 1
        else:
            other += 1

        # Modern emoji: vibrant and status-specific
        status_emoji = "🟢" if status == 'running' and not suspended_flag else "🟡" if suspended_flag else "🔴"
        vps_status = status.upper()
        if suspended_flag:
            vps_status += " (SUSPENDED)"
        if vps.get('whitelisted', False):
            vps_status += " (WHITELISTED)"
        config = vps.get('config', 'Custom')
        
        # Add expiration info
        expiration_info = ""
        if vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            if days_remaining < 0:
                expiration_info = " | 🔴 EXPIRED"
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                expiration_info = f" | 🟡 EXPIRES({days_remaining}d)"
            else:
                expiration_info = f" | 🟢 ({days_remaining}d)"
        else:
            expiration_info = " | ⏰ No exp"
        
        vps_info.append(f"{status_emoji} **{i}.** {username} • `{vps['container_name']}`\n _{vps_status} | {config}{expiration_info}_")

    # Create main embed (modern: gradient-inspired colors, clean typography)
    color = 0x10b981 if is_online else 0xef4444  # Teal green / Soft red for modern feel
    embed = create_embed(
        title=f"🖥️ VPS Dashboard - {node['name']}",
        description=f"**ID:** `{node_id}` | **Region:** {node['location']}\n*Updated: <t:{int(datetime.now().timestamp())}:R>*",
        color=color
    )
    embed.set_thumbnail(url=node.get('thumbnail_url', None))

    # Inline status and capacity for compact top row
    add_field(embed, "📡 **Status**", status, True)
    add_field(embed, "🗄️ **Capacity**", capacity_text, True)

    # Resources field with modern bar visualization
    add_field(embed, "📊 **Resources**", resources_text, False)

    # Summary field (modern: compact bullet-like with inline emojis)
    summary_text = (
        f"**Total:** {total_vps} 📊\n"
        f"**Running:** {running} 🟢\n"
        f"**Stopped:** {stopped} ⏸️\n"
        f"**Suspended:** {suspended} 🟡"
    )
    if other > 0:
        summary_text += f"\n**Other:** {other} ⚠️"
    add_field(embed, "📈 **Summary**", summary_text, True)

    # VPS List - chunked embeds with modern pagination
    if vps_info:
        chunk_size = 6  # Smaller chunks for cleaner mobile-friendly embeds
        chunks = [vps_info[i:i + chunk_size] for i in range(0, len(vps_info), chunk_size)]
        first_chunk_text = "\n".join(chunks[0])
        add_field(embed, "📋 **Active VPS (1/{len(chunks)})**", f"```{first_chunk_text}```", False)

        # Paginated follow-ups with consistent styling
        for idx, chunk in enumerate(chunks[1:], 2):
            page_embed = create_embed(
                title=f"🖥️ VPS Dashboard - {node['name']} (Page {idx}/{len(chunks)})",
                description=f"**ID:** `{node_id}` | **Region:** {node['location']}\n*Updated: <t:{int(datetime.now().timestamp())}:R>*",
                color=color
            )
            chunk_text = "\n".join(chunk)
            add_field(page_embed, "📋 **VPS List**", f"```{chunk_text}```", False)
            page_embed.set_footer(text=f"AxionHost • {len(vps_info)} VPS shown")
            await ctx.send(embed=page_embed)
    else:
        add_field(embed, "📋 **VPS List**", "No deployments yet. Launch one! 🚀", False)

    embed.set_footer(text=f"AxionHost • Total: {len(vps_info)} VPS")
    await ctx.send(embed=embed)

@bot.command(name='list-all')
@is_admin()
async def list_all_vps(ctx):
    total_vps = 0
    total_users = len(vps_data)
    running_vps = 0
    stopped_vps = 0
    suspended_vps = 0
    whitelisted_vps = 0
    vps_info = []
    user_summary = []
    for user_id, vps_list in vps_data.items():
        try:
            user = await bot.fetch_user(int(user_id))
            user_vps_count = len(vps_list)
            user_running = sum(1 for vps in vps_list if vps.get('status') == 'running' and not vps.get('suspended', False))
            user_stopped = sum(1 for vps in vps_list if vps.get('status') == 'stopped')
            user_suspended = sum(1 for vps in vps_list if vps.get('suspended', False))
            user_whitelisted = sum(1 for vps in vps_list if vps.get('whitelisted', False))
            total_vps += user_vps_count
            running_vps += user_running
            stopped_vps += user_stopped
            suspended_vps += user_suspended
            whitelisted_vps += user_whitelisted
            user_summary.append(f"**{user.name}** ({user.mention}) - {user_vps_count} VPS ({user_running} running, {user_suspended} suspended, {user_whitelisted} whitelisted)")
            for i, vps in enumerate(vps_list):
                node = get_node(vps['node_id'])
                node_name = node['name'] if node else "Unknown"
                status_emoji = "🟢" if vps.get('status') == 'running' and not vps.get('suspended', False) else "🟡" if vps.get('suspended', False) else "🔴"
                status_text = vps.get('status', 'unknown').upper()
                if vps.get('suspended', False):
                    status_text += " (SUSPENDED)"
                if vps.get('whitelisted', False):
                    status_text += " (WHITELISTED)"
                
                # Add expiration info
                expiration_text = ""
                if vps.get('expiration_date'):
                    expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                    days_remaining = (expiration_dt - datetime.now()).days
                    if days_remaining < 0:
                        expiration_text = " • 🔴 EXPIRED"
                    elif days_remaining <= EXPIRATION_WARNING_DAYS:
                        expiration_text = f" • 🟡 EXPIRING({days_remaining}d)"
                    else:
                        expiration_text = f" • 🟢 ({days_remaining}d)"
                else:
                    expiration_text = " • ⏰ No exp"
                
                vps_info.append(f"{status_emoji} **{user.name}** - VPS {i+1}: `{vps['container_name']}` - {vps.get('config', 'Custom')} - {status_text} (Node: {node_name}){expiration_text}")
        except discord.NotFound:
            vps_info.append(f"❓ Unknown User ({user_id}) - {len(vps_list)} VPS")
    embed = create_embed("All VPS Information", "Complete overview of all VPS deployments and user statistics", 0x1a1a1a)
    add_field(embed, "System Overview", f"**Total Users:** {total_users}\n**Total VPS:** {total_vps}\n**Running:** {running_vps}\n**Stopped:** {stopped_vps}\n**Suspended:** {suspended_vps}\n**Whitelisted:** {whitelisted_vps}", False)
    await ctx.send(embed=embed)
    if user_summary:
        embed = create_embed("User Summary", f"Summary of all users and their VPS", 0x1a1a1a)
        summary_text = "\n".join(user_summary)
        chunks = [summary_text[i:i+1024] for i in range(0, len(summary_text), 1024)]
        for idx, chunk in enumerate(chunks, 1):
            add_field(embed, f"Users (Part {idx})", chunk, False)
        await ctx.send(embed=embed)
    if vps_info:
        vps_text = "\n".join(vps_info)
        chunks = [vps_text[i:i+1024] for i in range(0, len(vps_text), 1024)]
        for idx, chunk in enumerate(chunks, 1):
            embed = create_embed(f"VPS Details (Part {idx})", "List of all VPS deployments", 0x1a1a1a)
            add_field(embed, "VPS List", chunk, False)
            await ctx.send(embed=embed)

@bot.command(name='manage-shared')
async def manage_shared_vps(ctx, owner: discord.Member, vps_number: int):
    owner_id = str(owner.id)
    user_id = str(ctx.author.id)
    if owner_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[owner_id]):
        await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number or owner doesn't have a VPS."))
        return
    vps = vps_data[owner_id][vps_number - 1]
    if user_id not in vps.get("shared_with", []):
        await ctx.send(embed=create_error_embed("Access Denied", "You do not have access to this VPS."))
        return
    view = ManageView(user_id, [vps], is_shared=True, owner_id=owner_id, actual_index=vps_number - 1)
    embed = await view.get_initial_embed()
    await ctx.send(embed=embed, view=view)

@bot.command(name='share-user')
async def share_user(ctx, shared_user: discord.Member, vps_number: int):
    user_id = str(ctx.author.id)
    shared_user_id = str(shared_user.id)
    if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
        await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number or you don't have a VPS."))
        return
    vps = vps_data[user_id][vps_number - 1]
    if "shared_with" not in vps:
        vps["shared_with"] = []
    if shared_user_id in vps["shared_with"]:
        await ctx.send(embed=create_error_embed("Already Shared", f"{shared_user.mention} already has access to this VPS!"))
        return
    vps["shared_with"].append(shared_user_id)
    save_vps_data()
    await ctx.send(embed=create_success_embed("VPS Shared", f"VPS #{vps_number} shared with {shared_user.mention}!"))
    try:
        await shared_user.send(embed=create_embed("VPS Access Granted", f"You have access to VPS #{vps_number} from {ctx.author.mention}. Use `{PREFIX}manage-shared {ctx.author.mention} {vps_number}`", 0x00ff88))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {shared_user.mention}"))

@bot.command(name='share-ruser')
async def revoke_share(ctx, shared_user: discord.Member, vps_number: int):
    user_id = str(ctx.author.id)
    shared_user_id = str(shared_user.id)
    if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
        await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number or you don't have a VPS."))
        return
    vps = vps_data[user_id][vps_number - 1]
    if "shared_with" not in vps:
        vps["shared_with"] = []
    if shared_user_id not in vps["shared_with"]:
        await ctx.send(embed=create_error_embed("Not Shared", f"{shared_user.mention} doesn't have access to this VPS!"))
        return
    vps["shared_with"].remove(shared_user_id)
    save_vps_data()
    await ctx.send(embed=create_success_embed("Access Revoked", f"Access to VPS #{vps_number} revoked from {shared_user.mention}!"))
    try:
        await shared_user.send(embed=create_embed("VPS Access Revoked", f"Your access to VPS #{vps_number} by {ctx.author.mention} has been revoked.", 0xff3366))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {shared_user.mention}"))

@bot.command(name='ports-add-user')
@is_admin()
async def ports_add_user(ctx, amount: int, user: discord.Member):
    if amount <= 0:
        await ctx.send(embed=create_error_embed("Invalid Amount", "Amount must be a positive integer."))
        return
    user_id = str(user.id)
    allocate_ports(user_id, amount)
    embed = create_success_embed("Ports Allocated", f"Allocated {amount} port slots to {user.mention}.")
    add_field(embed, "Quota", f"Total: {get_user_allocation(user_id)} slots", False)
    await ctx.send(embed=embed)
    try:
        dm_embed = create_info_embed("Port Slots Allocated", f"You have been granted {amount} additional port forwarding slots by an admin.\nUse `{PREFIX}ports list` to view your quota and active forwards.")
        await user.send(embed=dm_embed)
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("DM Failed", f"Could not notify {user.mention} via DM."))

@bot.command(name='ports-remove-user')
@is_admin()
async def ports_remove_user(ctx, amount: int, user: discord.Member):
    if amount <= 0:
        await ctx.send(embed=create_error_embed("Invalid Amount", "Amount must be a positive integer."))
        return
    user_id = str(user.id)
    current = get_user_allocation(user_id)
    if amount > current:
        amount = current
    deallocate_ports(user_id, amount)
    remaining = get_user_allocation(user_id)
    embed = create_success_embed("Ports Deallocated", f"Removed {amount} port slots from {user.mention}.")
    add_field(embed, "Remaining Quota", f"{remaining} slots", False)
    await ctx.send(embed=embed)
    try:
        dm_embed = create_warning_embed("Port Slots Reduced", f"Your port forwarding quota has been reduced by {amount} slots by an admin.\nRemaining: {remaining} slots.")
        await user.send(embed=dm_embed)
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("DM Failed", f"Could not notify {user.mention} via DM."))

@bot.command(name='ports-revoke')
@is_admin()
async def ports_revoke(ctx, forward_id: int):
    success, user_id = await remove_port_forward(forward_id, is_admin=True)
    if success and user_id:
        try:
            user = await bot.fetch_user(int(user_id))
            dm_embed = create_warning_embed("Port Forward Revoked", f"One of your port forwards (ID: {forward_id}) has been revoked by an admin.")
            await user.send(embed=dm_embed)
        except:
            pass
        await ctx.send(embed=create_success_embed("Revoked", f"Port forward ID {forward_id} revoked."))
    else:
        await ctx.send(embed=create_error_embed("Failed", "Port forward ID not found or removal failed."))

@bot.command(name='ports')
async def ports_command(ctx, subcmd: str = None, *args):
    user_id = str(ctx.author.id)
    allocated = get_user_allocation(user_id)
    used = get_user_used_ports(user_id)
    available = allocated - used
    if subcmd is None:
        embed = create_info_embed("Port Forwarding Help", f"**Your Quota:** Allocated: {allocated}, Used: {used}, Available: {available}")
        add_field(embed, "Commands", f"{PREFIX}ports add <vps_num> <port>\n{PREFIX}ports list\n{PREFIX}ports remove <id>", False)
        await ctx.send(embed=embed)
        return
    if subcmd == 'add':
        if len(args) < 2:
            await ctx.send(embed=create_error_embed("Usage", f"Usage: {PREFIX}ports add <vps_number> <vps_port>"))
            return
        try:
            vps_num = int(args[0])
            vps_port = int(args[1])
            if vps_port < 1 or vps_port > 65535:
                raise ValueError
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid Input", "VPS number and port must be positive integers (port: 1-65535)."))
            return
        vps_list = vps_data.get(user_id, [])
        if vps_num < 1 or vps_num > len(vps_list):
            await ctx.send(embed=create_error_embed("Invalid VPS", f"Invalid VPS number (1-{len(vps_list)}). Use {PREFIX}myvps to list."))
            return
        vps = vps_list[vps_num - 1]
        container = vps['container_name']
        node_id = vps['node_id']
        if used >= allocated:
            await ctx.send(embed=create_error_embed("Quota Exceeded", f"No available slots. Allocated: {allocated}, Used: {used}. Contact admin for more."))
            return
        host_port = await create_port_forward(user_id, container, vps_port, node_id)
        if host_port:
            embed = create_success_embed("Port Forward Created", f"VPS #{vps_num} port {vps_port} (TCP/UDP) forwarded to host port {host_port}.")
            add_field(embed, "Access", f"External: {YOUR_SERVER_IP}:{host_port} → VPS:{vps_port} (TCP & UDP)", False)
            add_field(embed, "Quota Update", f"Used: {used + 1}/{allocated}", False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=create_error_embed("Failed", "Could not assign host port. Try again later."))
    elif subcmd == 'list':
        forwards = get_user_forwards(user_id)
        embed = create_info_embed("Your Port Forwards", f"**Quota:** Allocated: {allocated}, Used: {used}, Available: {available}")
        if not forwards:
            add_field(embed, "Forwards", "No active port forwards.", False)
        else:
            text = []
            for f in forwards:
                vps_num = next((i+1 for i, v in enumerate(vps_data.get(user_id, [])) if v['container_name'] == f['vps_container']), 'Unknown')
                created = datetime.fromisoformat(f['created_at']).strftime('%Y-%m-%d %H:%M')
                text.append(f"**ID {f['id']}** - VPS #{vps_num}: {f['vps_port']} (TCP/UDP) → {f['host_port']} (Created: {created})")
            add_field(embed, "Active Forwards", "\n".join(text[:10]), False)
            if len(forwards) > 10:
                add_field(embed, "Note", f"Showing 10 of {len(forwards)}. Remove unused with {PREFIX}ports remove <id>.")
        await ctx.send(embed=embed)
    elif subcmd == 'remove':
        if len(args) < 1:
            await ctx.send(embed=create_error_embed("Usage", f"Usage: {PREFIX}ports remove <forward_id>"))
            return
        try:
            fid = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid ID", "Forward ID must be an integer."))
            return
        success, _ = await remove_port_forward(fid)
        if success:
            embed = create_success_embed("Removed", f"Port forward {fid} removed (TCP & UDP).")
            add_field(embed, "Quota Update", f"Used: {used - 1}/{allocated}", False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=create_error_embed("Not Found", "Forward ID not found. Use !ports list."))
    else:
        await ctx.send(embed=create_error_embed("Invalid Subcommand", f"Use: add <vps_num> <port>, list, remove <id>"))

class ConfirmDeleteView(discord.ui.View):
    """Confirmation dialog for VPS deletion"""
    def __init__(self, admin_id: str, vps_id: int, container_name: str, vps_number: int):
        super().__init__(timeout=60)  # 60 seconds to confirm
        self.admin_id = admin_id  # Admin who initiated the delete command
        self.vps_id = vps_id
        self.container_name = container_name
        self.vps_number = vps_number
        self.confirmed = False
    
    @discord.ui.button(label="✅ Confirm Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Allow only the admin who initiated the delete command to confirm
        if str(interaction.user.id) != self.admin_id:
            await interaction.response.send_message(
                embed=create_error_embed("Access Denied", "Only the admin who initiated the deletion can confirm!"),
                ephemeral=True
            )
            return
        
        self.confirmed = True
        await interaction.response.defer()
        self.stop()
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Allow only the admin who initiated the delete command to cancel
        if str(interaction.user.id) != self.admin_id:
            await interaction.response.send_message(
                embed=create_error_embed("Access Denied", "Only the admin who initiated the deletion can cancel!"),
                ephemeral=True
            )
            return
        
        await interaction.response.send_message(
            embed=create_info_embed("Deletion Cancelled", f"VPS deletion for {self.container_name} has been cancelled."),
            ephemeral=True
        )
        self.stop()

@bot.command(name='delete-vps')
@is_admin()
async def delete_vps(ctx, user: discord.Member, vps_number: int, *, reason: str = "No reason"):
    user_id = str(user.id)

    if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
        await ctx.send(embed=create_error_embed(
            "Invalid VPS",
            "Invalid VPS number or user doesn't have that VPS."
        ))
        return

    vps = vps_data[user_id][vps_number - 1]
    container_name = vps["container_name"]
    vps_id = vps.get("id", vps_number)
    node_id = vps.get("node_id", 1)

    # Create confirmation embed with clearer info
    confirm_embed = create_embed("⚠️ Confirm VPS Deletion", f"Are you sure you want to delete this VPS?", 0xff3366)
    add_field(confirm_embed, "VPS Details", 
        f"**VPS ID:** #{vps_id}\n"
        f"**Container:** `{container_name}`\n"
        f"**Owner:** {user.mention}\n"
        f"**Config:** {vps.get('config', 'Custom')}\n"
        f"**Status:** {vps.get('status', 'unknown').upper()}", 
        False)
    add_field(confirm_embed, "Action", "Click **✅ Confirm Delete** to permanently delete this VPS, or **❌ Cancel** to abort.", False)
    add_field(confirm_embed, "Reason", reason, False)
    
    confirmation_view = ConfirmDeleteView(str(ctx.author.id), vps_id, container_name, vps_number)
    confirmation_msg = await ctx.send(embed=confirm_embed, view=confirmation_view)
    
    # Wait for confirmation
    await confirmation_view.wait()
    
    if not confirmation_view.confirmed:
        return  # User cancelled or timeout
    
    # Proceed with deletion
    await ctx.send(embed=create_info_embed(
        "🗑️ Deleting VPS",
        f"Removing VPS #{vps_id} for {user.mention}..."
    ))

    node_result = "Not checked"

    # 1️⃣ Try deleting container
    try:
        await execute_lxc(container_name, f"delete {container_name} --force", node_id=node_id)
        node_result = "Container deleted successfully."
    except Exception as e:
        err = str(e).lower()
        if any(x in err for x in ["not found", "does not exist", "no such container"]):
            node_result = "Container not found (force DB cleanup)."
        else:
            node_result = f"Container delete failed: {e}"

    # 2️⃣ DELETE FROM DATABASE
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM vps WHERE container_name = ?", (container_name,))
    cur.execute("DELETE FROM port_forwards WHERE vps_container = ?", (container_name,))

    conn.commit()
    conn.close()

    # 3️⃣ Remove from memory
    del vps_data[user_id][vps_number - 1]
    if not vps_data[user_id]:
        del vps_data[user_id]

        # Remove VPS role if needed
        if ctx.guild:
            role = await get_or_create_vps_role(ctx.guild)
            if role and role in user.roles:
                try:
                    await user.remove_roles(role, reason="No VPS ownership")
                except discord.Forbidden:
                    logger.warning(f"Failed to remove VPS role from {user.name}")

    save_vps_data()

    # 4️⃣ Success embed
    embed = create_success_embed("✅ VPS Deleted Successfully")
    add_field(embed, "VPS ID", f"#{vps_id}", True)
    add_field(embed, "Owner", user.mention, True)
    add_field(embed, "Container", container_name, False)
    add_field(embed, "Node Result", node_result, False)
    add_field(embed, "Reason", reason, False)

    await ctx.send(embed=embed)

@bot.command(name='add-resources')
@is_admin()
async def add_resources(ctx, vps_id: str, ram: int = None, cpu: int = None, disk: int = None):
    for label, value in (("RAM", ram), ("CPU", cpu), ("Disk", disk)):
        if value is not None and int(value) <= 0:
            await ctx.send(embed=create_error_embed("Invalid Resource Value", f"{label} must be a positive whole number."))
            return
    if ram is None and cpu is None and disk is None:
        await ctx.send(embed=create_error_embed("Missing Parameters", "Please specify at least one resource to add (ram, cpu, or disk)"))
        return
    found_vps = None
    user_id = None
    vps_index = None
    for uid, vps_list in vps_data.items():
        for i, vps in enumerate(vps_list):
            if vps['container_name'] == vps_id:
                found_vps = vps
                user_id = uid
                vps_index = i
                break
        if found_vps:
            break
    if not found_vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with ID: `{vps_id}`"))
        return
    node_id = found_vps['node_id']
    was_running = found_vps.get('status') == 'running' and not found_vps.get('suspended', False)
    disk_changed = disk is not None
    if was_running:
        await ctx.send(embed=create_info_embed("Stopping VPS", f"Stopping VPS `{vps_id}` to apply resource changes..."))
        try:
            await execute_lxc(vps_id, f"stop {vps_id}", node_id=node_id)
            found_vps['status'] = 'stopped'
            save_vps_data()
        except Exception as e:
            await ctx.send(embed=create_error_embed("Stop Failed", f"Error stopping VPS: {str(e)}"))
            return
    changes = []
    try:
        current_ram_gb = int(found_vps['ram'].replace('GB', ''))
        current_cpu = int(found_vps['cpu'])
        current_disk_gb = int(found_vps['storage'].replace('GB', ''))
        new_ram_gb = current_ram_gb
        new_cpu = current_cpu
        new_disk_gb = current_disk_gb
        if ram is not None and ram > 0:
            new_ram_gb += ram
            ram_mb = new_ram_gb * 1024
            await execute_lxc(vps_id, f"config set {vps_id} limits.memory {ram_mb}MB", node_id=node_id)
            changes.append(f"RAM: +{ram}GB (New total: {new_ram_gb}GB)")
        if cpu is not None and cpu > 0:
            new_cpu += cpu
            await execute_lxc(vps_id, f"config set {vps_id} limits.cpu {new_cpu}", node_id=node_id)
            changes.append(f"CPU: +{cpu} cores (New total: {new_cpu} cores)")
        if disk is not None and disk > 0:
            new_disk_gb += disk
            await execute_lxc(vps_id, f"config device set {vps_id} root size={new_disk_gb}GB", node_id=node_id)
            changes.append(f"Disk: +{disk}GB (New total: {new_disk_gb}GB)")
        found_vps['ram'] = f"{new_ram_gb}GB"
        found_vps['cpu'] = str(new_cpu)
        found_vps['storage'] = f"{new_disk_gb}GB"
        found_vps['config'] = f"{new_ram_gb}GB RAM / {new_cpu} CPU / {new_disk_gb}GB Disk"
        vps_data[user_id][vps_index] = found_vps
        save_vps_data()
        if was_running:
            await execute_lxc(vps_id, f"start {vps_id}", node_id=node_id)
            found_vps['status'] = 'running'
            save_vps_data()
            await apply_internal_permissions(vps_id, node_id)
            await recreate_port_forwards(vps_id)
        embed = create_success_embed("Resources Added", f"Successfully added resources to VPS `{vps_id}`")
        add_field(embed, "Changes Applied", "\n".join(changes), False)
        if disk_changed:
            add_field(embed, "Disk Note", "The virtual disk size was updated. Expand the guest partition/filesystem inside the VPS (for example, use `growpart` and `resize2fs` on ext4, or the matching tool for your filesystem).", False)
        await ctx.send(embed=embed)
    except Exception as e:
        if was_running:
            try:
                await execute_lxc(vps_id, f"start {vps_id}", node_id=node_id)
                found_vps['status'] = 'running'
                save_vps_data_immediate()
            except Exception as restart_error:
                logger.error('Could not restore VPS %s after resource-add failure: %s', vps_id, restart_error)
        await ctx.send(embed=create_error_embed("Resource Addition Failed", f"Error: {str(e)}"))


@bot.command(name='status')
@is_admin()
async def system_status(ctx):
    """
    Show complete system status including:
    - Bot uptime
    - Total nodes & their status
    - Running/stopped nodes count
    - Total RAM/CPU/DISK allocated vs free
    - Total VPS & users
    - Running/stopped/suspended VPS counts
    - Total admin users
    - Whitelisted VPS
    """
    
    # Start timing for response time
    start_time = time.time()
    
    # Get bot uptime
    bot_start_time = datetime.now() - datetime.fromtimestamp(start_time - bot.latency)
    bot_uptime = str(bot_start_time).split('.')[0]  # Remove microseconds
    
    # Get total nodes
    nodes = get_nodes()
    total_nodes = len(nodes)
    
    # Node status counters
    running_nodes = 0
    stopped_nodes = 0
    local_nodes = 0
    remote_nodes = 0
    
    # Node resource tracking
    total_node_cpu_allocated = 0
    total_node_ram_allocated = 0
    total_node_disk_allocated = 0
    total_node_cpu_free = 0
    total_node_ram_free = 0
    total_node_disk_free = 0
    
    # VPS counters
    total_vps = 0
    total_users = len(vps_data)
    running_vps = 0
    stopped_vps = 0
    suspended_vps = 0
    whitelisted_vps = 0
    
    # Admin counters
    total_admins = len(admin_data.get("admins", [])) + 1  # +1 for main admin
    
    # Port statistics
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT SUM(allocated_ports) FROM port_allocations")
    total_ports_allocated = cur.fetchone()[0] or 0
    cur.execute("SELECT COUNT(*) FROM port_forwards")
    total_ports_used = cur.fetchone()[0] or 0
    conn.close()
    
    # Resource counters for all VPS
    total_ram_allocated = 0
    total_cpu_allocated = 0
    total_disk_allocated = 0
    
    # Process all VPS data
    for user_id, vps_list in vps_data.items():
        total_vps += len(vps_list)
        
        for vps in vps_list:
            # Count status
            if vps.get('suspended', False):
                suspended_vps += 1
            elif vps.get('status') == 'running':
                running_vps += 1
            else:
                stopped_vps += 1
            
            # Count whitelisted
            if vps.get('whitelisted', False):
                whitelisted_vps += 1
            
            # Calculate allocated resources
            try:
                ram_gb = int(vps['ram'].replace('GB', ''))
                total_ram_allocated += ram_gb
            except:
                pass
            
            try:
                cpu_cores = int(vps['cpu'])
                total_cpu_allocated += cpu_cores
            except:
                pass
            
            try:
                disk_gb = int(vps['storage'].replace('GB', ''))
                total_disk_allocated += disk_gb
            except:
                pass
    
    # Check node status and calculate free resources
    node_statuses = []
    
    for node in nodes:
        # Determine node type
        if node['is_local']:
            local_nodes += 1
            node_type = "🖥️ Local"
        else:
            remote_nodes += 1
            node_type = "🌐 Remote"
        
        # Check node status
        if node['is_local']:
            status = "🟢 Online"
            running_nodes += 1
            
            # Get local resources (approximate) - cross-platform
            try:
                import platform
                system = platform.system()
                
                if system == "Windows":
                    # Windows: Use psutil
                    try:
                        import psutil
                        mem = psutil.virtual_memory()
                        total_ram_gb = mem.total / (1024**3)
                        free_ram_gb = mem.available / (1024**3)
                        
                        cpu_count = psutil.cpu_count()
                        total_cpu = cpu_count if cpu_count else 0
                        
                        disk = psutil.disk_usage('C:\\' if 'C:\\' else '/')
                        total_disk = disk.total / (1024**3)
                    except ImportError:
                        # Fallback for Windows without psutil
                        try:
                            result = subprocess.run(['wmic', 'OS', 'get', 'TotalVisibleMemorySize,FreePhysicalMemory'], 
                                                  capture_output=True, text=True, timeout=5)
                            lines = result.stdout.strip().split('\n')
                            if len(lines) > 1:
                                values = lines[1].split()
                                total_ram_gb = int(values[0]) / (1024**2)
                                free_ram_gb = int(values[1]) / (1024**2)
                            else:
                                total_ram_gb = 0
                                free_ram_gb = 0
                            
                            result = subprocess.run(['wmic', 'os', 'get', 'numberofprocessors'], 
                                                  capture_output=True, text=True, timeout=5)
                            total_cpu = int(result.stdout.strip().split('\n')[-1]) if result.stdout else 0
                            
                            total_disk = 0  # Approximate
                        except:
                            total_ram_gb = 0
                            free_ram_gb = 0
                            total_cpu = 0
                            total_disk = 0
                else:
                    # Linux/Unix: Use traditional commands
                    # Get system memory
                    mem_result = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=10)
                    mem_lines = mem_result.stdout.splitlines()
                    if len(mem_lines) > 1:
                        mem = mem_lines[1].split()
                        total_ram_mb = int(mem[1])
                        used_ram_mb = int(mem[2])
                        free_ram_mb = total_ram_mb - used_ram_mb
                        total_ram_gb = total_ram_mb / 1024
                        free_ram_gb = free_ram_mb / 1024
                    else:
                        total_ram_gb = 0
                        free_ram_gb = 0
                    
                    # Get CPU cores
                    cpu_result = subprocess.run(['nproc'], capture_output=True, text=True, timeout=10)
                    total_cpu = int(cpu_result.stdout.strip()) if cpu_result.stdout.strip() else 0
                    
                    # Get disk space
                    disk_result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=10)
                    disk_lines = disk_result.stdout.splitlines()
                    if len(disk_lines) > 1:
                        disk_parts = disk_lines[1].split()
                        total_disk_str = disk_parts[1]
                        # Convert to GB
                        if 'T' in total_disk_str:
                            total_disk = float(total_disk_str.replace('T', '')) * 1024
                        elif 'G' in total_disk_str:
                            total_disk = float(total_disk_str.replace('G', ''))
                        elif 'M' in total_disk_str:
                            total_disk = float(total_disk_str.replace('M', '')) / 1024
                        else:
                            total_disk = 0
                    else:
                        total_disk = 0
                
                # Calculate free resources (simplified - actual would need more complex logic)
                free_cpu = max(0, total_cpu - (total_cpu_allocated // total_nodes)) if total_nodes > 0 else 0
                free_disk = max(0, total_disk - (total_disk_allocated // total_nodes)) if total_nodes > 0 else 0
                
                # Update totals
                if total_ram_gb > 0:
                    total_node_ram_allocated += total_ram_gb - free_ram_gb
                    total_node_ram_free += free_ram_gb
                if total_cpu > 0:
                    total_node_cpu_allocated += total_cpu - free_cpu
                    total_node_cpu_free += free_cpu
                if total_disk > 0:
                    total_node_disk_allocated += total_disk - free_disk
                    total_node_disk_free += free_disk
                
            except Exception as e:
                logger.debug(f"Error getting local node resources: {e}")
                status = "⚠️ Unknown"
                # Don't reset to 0, just skip this node's resources
        else:
            # Check remote node status
            try:
                response = await http_request('GET', f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
                if response.status_code == 200:
                    status = "🟢 Online"
                    running_nodes += 1
                else:
                    status = "🔴 Offline"
                    stopped_nodes += 1
            except:
                status = "🔴 Offline"
                stopped_nodes += 1
        
        # Get current VPS count on this node
        node_vps_count = get_current_vps_count(node['id'])
        capacity = node['total_vps']
        usage_percentage = (node_vps_count / capacity * 100) if capacity > 0 else 0
        
        node_statuses.append(
            f"**{node['name']}** ({node_type})\n"
            f"📍 {node['location']} • 📊 {node_vps_count}/{capacity} VPS ({usage_percentage:.0f}%)\n"
            f"Status: {status}"
        )
    
    # Calculate response time
    response_time = (time.time() - start_time) * 1000
    
    # Create main embed
    embed = create_embed(
        title="📊 System Status Dashboard",
        description=f"**{BOT_NAME}** - Complete System Overview\n*Generated in {response_time:.0f}ms*",
        color=0x1a1a1a
    )
    
    # Bot & Uptime Section
    add_field(embed, "🤖 Bot Status", 
        f"**Uptime:** {bot_uptime}\n"
        f"**Latency:** {round(bot.latency * 1000)}ms\n"
        f"**Version:** {BOT_VERSION}\n"
        f"**Developer:** {BOT_DEVELOPER}", 
        True)
    
    # Nodes Section
    add_field(embed, "🌐 Nodes Overview",
        f"**Total Nodes:** {total_nodes}\n"
        f"**Running:** {running_nodes} 🟢\n"
        f"**Stopped:** {stopped_nodes} 🔴\n"
        f"**Local/Remote:** {local_nodes}/{remote_nodes}",
        True)
    
    # VPS & Users Section
    add_field(embed, "👥 Users & VPS",
        f"**Total Users:** {total_users}\n"
        f"**Total VPS:** {total_vps}\n"
        f"**Running:** {running_vps} 🟢\n"
        f"**Stopped:** {stopped_vps} 🔴\n"
        f"**Suspended:** {suspended_vps} 🟡\n"
        f"**Whitelisted:** {whitelisted_vps} ✅",
        True)
    
    # Resources Section - Allocated vs Free
    add_field(embed, "💾 Resource Allocation",
        f"**RAM Allocated:** {total_ram_allocated} GB\n"
        f"**RAM Free:** {total_node_ram_free:.1f} GB\n"
        f"**CPU Allocated:** {total_cpu_allocated} Cores\n"
        f"**CPU Free:** {total_node_cpu_free:.1f} Cores\n"
        f"**Disk Allocated:** {total_disk_allocated} GB\n"
        f"**Disk Free:** {total_node_disk_free:.1f} GB",
        True)
    
    # System & Admin Section
    add_field(embed, "⚙️ System Information",
        f"**Total Admins:** {total_admins}\n"
        f"**Main Admin:** <@{MAIN_ADMIN_ID}>\n"
        f"**Ports Allocated:** {total_ports_allocated}\n"
        f"**Ports In Use:** {total_ports_used}\n"
        f"**Ports Available:** {total_ports_allocated - total_ports_used}",
        True)
    
    # Node Details Section (if any nodes exist)
    if node_statuses:
        # Split node statuses into chunks if too long
        node_text = "\n\n".join(node_statuses)
        chunks = [node_text[i:i+1024] for i in range(0, len(node_text), 1024)]
        
        for idx, chunk in enumerate(chunks, 1):
            title = "📡 Node Details" if idx == 1 else f"📡 Node Details (Part {idx})"
            add_field(embed, title, chunk, False)
    
    # Expiration Status Section
    expiring_soon_count = 0
    expired_count = 0
    active_exp_count = 0
    no_exp_count = 0
    
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps.get('expiration_date'):
                expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                days_remaining = (expiration_dt - datetime.now()).days
                if days_remaining < 0:
                    expired_count += 1
                elif days_remaining <= EXPIRATION_WARNING_DAYS:
                    expiring_soon_count += 1
                else:
                    active_exp_count += 1
            else:
                no_exp_count += 1
    
    add_field(embed, "⏰ VPS Expiration Status",
        f"**🟢 Active:** {active_exp_count} VPS\n"
        f"**🟡 Expiring Soon:** {expiring_soon_count} VPS\n"
        f"**🔴 Expired:** {expired_count} VPS\n"
        f"**🔵 No Expiration:** {no_exp_count} VPS",
        True)
    
    # System Health Indicator
    health_status = "✅ Excellent"
    health_color = 0x00ff88
    
    if running_nodes == 0:
        health_status = "🔴 Critical - No nodes running"
        health_color = 0xff3366
    elif stopped_nodes > 0:
        health_status = "🟡 Warning - Some nodes offline"
        health_color = 0xffaa00
    elif total_vps == 0:
        health_status = "ℹ️ No VPS deployed"
        health_color = 0x00ccff
    
    add_field(embed, "🏥 System Health", health_status, False)
    
    # Footer with current time
    embed.set_footer(text=f"AxionHost • System Status • Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    icon_url=BOT_ICON_URL)
    
    await ctx.send(embed=embed)


@bot.command(name='status-summary')
@is_admin()
async def status_summary(ctx):
    """
    Quick summary of system status
    """
    # Get quick stats
    nodes = get_nodes()
    total_nodes = len(nodes)
    running_nodes = 0
    
    for node in nodes:
        if node['is_local']:
            running_nodes += 1
        else:
            try:
                response = await http_request('GET', f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=3)
                if response.status_code == 200:
                    running_nodes += 1
            except:
                pass
    
    total_vps = sum(len(vps_list) for vps_list in vps_data.values())
    total_users = len(vps_data)
    
    # Count VPS status
    running_vps = 0
    stopped_vps = 0
    suspended_vps = 0
    
    for vps_list in vps_data.values():
        for vps in vps_list:
            if vps.get('suspended', False):
                suspended_vps += 1
            elif vps.get('status') == 'running':
                running_vps += 1
            else:
                stopped_vps += 1
    
    embed = create_success_embed(
        "📈 Quick Status Summary",
        f"**Nodes:** {running_nodes}/{total_nodes} 🟢\n"
        f"**VPS:** {total_vps} total\n"
        f"• Running: {running_vps} 🟢\n"
        f"• Stopped: {stopped_vps} 🔴\n"
        f"• Suspended: {suspended_vps} 🟡\n"
        f"**Users:** {total_users} 👥\n"
        f"**Bot Latency:** {round(bot.latency * 1000)}ms"
    )
    
    embed.set_footer(text=f"Use '{PREFIX}status' for detailed information")
    await ctx.send(embed=embed)

@bot.command(name='admin-add')
@is_main_admin()
async def admin_add(ctx, user: discord.Member):
    user_id = str(user.id)
    if user_id == str(MAIN_ADMIN_ID):
        await ctx.send(embed=create_error_embed("Already Admin", "This user is already the main admin!"))
        return
    if user_id in admin_data.get("admins", []):
        await ctx.send(embed=create_error_embed("Already Admin", f"{user.mention} is already an admin!"))
        return
    admin_data["admins"].append(user_id)
    save_admin_data()
    await ctx.send(embed=create_success_embed("Admin Added", f"{user.mention} is now an admin!"))
    try:
        await user.send(embed=create_embed("🎉 Admin Role Granted", f"You are now an admin by {ctx.author.mention}", 0x00ff88))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {user.mention}"))

@bot.command(name='admin-remove')
@is_main_admin()
async def admin_remove(ctx, user: discord.Member):
    user_id = str(user.id)
    if user_id == str(MAIN_ADMIN_ID):
        await ctx.send(embed=create_error_embed("Cannot Remove", "You cannot remove the main admin!"))
        return
    if user_id not in admin_data.get("admins", []):
        await ctx.send(embed=create_error_embed("Not Admin", f"{user.mention} is not an admin!"))
        return
    admin_data["admins"].remove(user_id)
    save_admin_data()
    await ctx.send(embed=create_success_embed("Admin Removed", f"{user.mention} is no longer an admin!"))
    try:
        await user.send(embed=create_embed("⚠️ Admin Role Revoked", f"Your admin role was removed by {ctx.author.mention}", 0xff3366))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {user.mention}"))

@bot.command(name='admin-list')
@is_main_admin()
async def admin_list(ctx):
    admins = admin_data.get("admins", [])
    main_admin = await bot.fetch_user(MAIN_ADMIN_ID)
    embed = create_embed("👑 Admin Team", "Current administrators:", 0x1a1a1a)
    add_field(embed, "🔰 Main Admin", f"{main_admin.mention} (ID: {MAIN_ADMIN_ID})", False)
    if admins:
        admin_list = []
        for admin_id in admins:
            try:
                admin_user = await bot.fetch_user(int(admin_id))
                admin_list.append(f"• {admin_user.mention} (ID: {admin_id})")
            except:
                admin_list.append(f"• Unknown User (ID: {admin_id})")
        admin_text = "\n".join(admin_list)
        add_field(embed, "🛡️ Admins", admin_text, False)
    else:
        add_field(embed, "🛡️ Admins", "No additional admins", False)
    await ctx.send(embed=embed)

@bot.command(name="userinfo")
@is_admin()
async def user_info(ctx, user: discord.Member):
    user_id = str(user.id)
    vps_list = vps_data.get(user_id, [])

    # ─── Embed ─────────────────────────────────────────────────
    embed = create_embed(
        title="👤 User Dashboard",
        description=f"Statistics & resources for {user.mention}",
        color=0x1A1A1A
    )

    # ─── Row 1 : User Info ─────────────────────────────────────
    embed.add_field(
        name="👤 User",
        value=(
            f"**Name:** `{user.name}`\n"
            f"**ID:** `{user.id}`\n"
            f"**Joined:** `{user.joined_at.strftime('%Y-%m-%d') if user.joined_at else 'Unknown'}`"
        ),
        inline=True
    )

    is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
    embed.add_field(
        name="🛡️ Admin",
        value="✅ Yes" if is_admin_user else "❌ No",
        inline=True
    )

    embed.add_field(
        name="🖥️ VPS Count",
        value=f"`{len(vps_list)}` VPS",
        inline=True
    )

    # ─── If VPS Exists ─────────────────────────────────────────
    if vps_list:
        total_ram = total_cpu = total_storage = 0
        running = suspended = whitelisted = 0

        vps_lines = []

        for i, vps in enumerate(vps_list, start=1):
            node = get_node(vps.get("node_id"))
            node_name = node["name"] if node else "Unknown"

            ram = int(vps.get("ram", "0GB").replace("GB", ""))
            storage = int(vps.get("storage", "0GB").replace("GB", ""))
            cpu = int(vps.get("cpu", 0))

            total_ram += ram
            total_storage += storage
            total_cpu += cpu

            if vps.get("suspended"):
                status = "⛔ SUSPENDED"
                suspended += 1
            elif vps.get("status") == "running":
                status = "🟢 RUNNING"
                running += 1
            else:
                status = "🔴 STOPPED"

            if vps.get("whitelisted"):
                whitelisted += 1

            vps_lines.append(
                f"**{i}.** `{vps['container_name']}`\n"
                f"{status} | `{ram}GB` RAM • `{cpu}` CPU • `{storage}GB` Disk\n"
                f"📍 Node: `{node_name}`" + 
                (f"\n⏰ {('🔴 EXPIRED' if (datetime.fromisoformat(vps['expiration_date']) - datetime.now()).days < 0 else '🟡 EXPIRING' if (datetime.fromisoformat(vps['expiration_date']) - datetime.now()).days <= EXPIRATION_WARNING_DAYS else '🟢 ACTIVE')} • {(datetime.fromisoformat(vps['expiration_date']).strftime('%Y-%m-%d'))} ({max(0, (datetime.fromisoformat(vps['expiration_date']) - datetime.now()).days)}d)" if vps.get('expiration_date') else "\n⏰ No expiration set")
            )

        # ─── Row 2 : VPS Summary ────────────────────────────────
        embed.add_field(
            name="📊 VPS Summary",
            value=(
                f"🖥️ `{len(vps_list)}` Total\n"
                f"🟢 `{running}` Running\n"
                f"⛔ `{suspended}` Suspended\n"
                f"✅ `{whitelisted}` Whitelisted"
            ),
            inline=True
        )

        embed.add_field(
            name="📈 Resources",
            value=(
                f"**RAM:** `{total_ram} GB`\n"
                f"**CPU:** `{total_cpu} Cores`\n"
                f"**Disk:** `{total_storage} GB`"
            ),
            inline=True
        )

        port_quota = get_user_allocation(user_id)
        port_used = get_user_used_ports(user_id)

        embed.add_field(
            name="🌐 Ports",
            value=f"`{port_used}/{port_quota}` Used",
            inline=True
        )

        # ─── VPS List (Split if needed) ────────────────────────
        vps_text = "\n\n".join(vps_lines)
        for i in range(0, len(vps_text), 1024):
            embed.add_field(
                name="📋 VPS List",
                value=vps_text[i:i + 1024],
                inline=False
            )

    else:
        embed.add_field(
            name="🖥️ VPS",
            value="❌ No VPS assigned",
            inline=False
        )

    embed.set_footer(text="AxionHost • User Resource Dashboard")
    embed.timestamp = ctx.message.created_at

    await ctx.send(embed=embed)

@bot.command(name="serverstats")
@is_admin()
async def server_stats(ctx):
    # ─── Counts ────────────────────────────────────────────────
    total_users = len(vps_data)
    total_admins = len(admin_data.get("admins", [])) + 1
    total_vps = sum(len(vps_list) for vps_list in vps_data.values())

    total_ram = total_cpu = total_storage = 0
    running_vps = suspended_vps = stopped_vps = 0
    whitelisted_vps = 0

    # ─── VPS Data ──────────────────────────────────────────────
    for vps_list in vps_data.values():
        for vps in vps_list:
            total_ram += int(vps.get("ram", "0GB").replace("GB", ""))
            total_storage += int(vps.get("storage", "0GB").replace("GB", ""))
            total_cpu += int(vps.get("cpu", 0))

            if vps.get("status") == "running":
                if vps.get("suspended", False):
                    suspended_vps += 1
                else:
                    running_vps += 1
            else:
                stopped_vps += 1

            if vps.get("whitelisted", False):
                whitelisted_vps += 1

    # ─── Ports ─────────────────────────────────────────────────
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT SUM(allocated_ports) FROM port_allocations")
    total_ports_allocated = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM port_forwards")
    total_ports_used = cur.fetchone()[0] or 0
    conn.close()

    # ─── Embed ─────────────────────────────────────────────────
    embed = create_embed(
        title="📊 Server Statistics",
        description="**Live Infrastructure Dashboard**",
        color=0x1A1A1A
    )

    # ── Row 1 ──────────────────────────────────────────────────
    embed.add_field(
        name="👥 Users",
        value=f"`{total_users}` Users\n`{total_admins}` Admins",
        inline=True
    )

    embed.add_field(
        name="🖥️ VPS",
        value=(
            f"Total: `{total_vps}`\n"
            f"🟢 `{running_vps}` Running\n"
            f"⛔ `{suspended_vps}` Suspended"
        ),
        inline=True
    )

    embed.add_field(
        name="📌 Status",
        value=(
            f"🔴 `{stopped_vps}` Stopped\n"
            f"✅ `{whitelisted_vps}` Whitelisted"
        ),
        inline=True
    )

    # ── Row 2 ──────────────────────────────────────────────────
    embed.add_field(
        name="📈 RAM",
        value=f"`{total_ram} GB`",
        inline=True
    )

    embed.add_field(
        name="⚙️ CPU",
        value=f"`{total_cpu} Cores`",
        inline=True
    )

    embed.add_field(
        name="💾 Storage",
        value=f"`{total_storage} GB`",
        inline=True
    )

    # ─── Expiration Counts ─────────────────────────────────────
    expiring_soon_count = 0
    expired_count = 0
    active_exp_count = 0
    no_exp_count = 0
    
    for vps_list in vps_data.values():
        for vps in vps_list:
            if vps.get('expiration_date'):
                expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                days_remaining = (expiration_dt - datetime.now()).days
                if days_remaining < 0:
                    expired_count += 1
                elif days_remaining <= EXPIRATION_WARNING_DAYS:
                    expiring_soon_count += 1
                else:
                    active_exp_count += 1
            else:
                no_exp_count += 1

    # ── Row 3 ──────────────────────────────────────────────────
    embed.add_field(
        name="⏰ Expiration",
        value=(
            f"🟢 `{active_exp_count}` Active\n"
            f"🟡 `{expiring_soon_count}` Expiring Soon\n"
            f"🔴 `{expired_count}` Expired\n"
            f"🔵 `{no_exp_count}` No Exp"
        ),
        inline=True
    )

    embed.add_field(
        name="🌐 Ports Allocated",
        value=f"`{total_ports_allocated}`",
        inline=True
    )

    embed.add_field(
        name="🔌 Ports In Use",
        value=f"`{total_ports_used}`",
        inline=True
    )

    # ── Row 4 ──────────────────────────────────────────────────

    # ── Row 4 ──────────────────────────────────────────────────
    embed.add_field(
        name="📊 Port Utilization",
        value=(
            f"`{total_ports_used}/{total_ports_allocated}`"
            if total_ports_allocated else "`N/A`"
        ),
        inline=True
    )

    embed.set_footer(text="AxionHost • Real-Time Monitoring")
    embed.timestamp = ctx.message.created_at

    await ctx.send(embed=embed)

@bot.command(name='vpsinfo')
@is_admin()
async def vps_info(ctx, container_name: str = None):
    if not container_name:
        all_vps = []
        for user_id, vps_list in vps_data.items():
            try:
                user = await bot.fetch_user(int(user_id))
                for i, vps in enumerate(vps_list):
                    node = get_node(vps['node_id'])
                    node_name = node['name'] if node else "Unknown"
                    status_text = vps.get('status', 'unknown').upper()
                    if vps.get('suspended', False):
                        status_text += " (SUSPENDED)"
                    if vps.get('whitelisted', False):
                        status_text += " (WHITELISTED)"
                    
                    # Add expiration info
                    expiration_text = ""
                    if vps.get('expiration_date'):
                        expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                        days_remaining = (expiration_dt - datetime.now()).days
                        if days_remaining < 0:
                            expiration_text = " • 🔴 EXPIRED"
                        elif days_remaining <= EXPIRATION_WARNING_DAYS:
                            expiration_text = f" • 🟡 EXPIRING ({days_remaining}d)"
                        else:
                            expiration_text = f" • 🟢 ({days_remaining}d)"
                    
                    all_vps.append(f"**{user.name}** - VPS {i+1}: `{vps['container_name']}` - {status_text} (Node: {node_name}){expiration_text}")
            except:
                pass
        vps_text = "\n".join(all_vps)
        chunks = [vps_text[i:i+1024] for i in range(0, len(vps_text), 1024)]
        for idx, chunk in enumerate(chunks, 1):
            embed = create_embed(f"🖥️ All VPS (Part {idx}/{len(chunks)})", f"Complete list of all VPS deployments with expiration status", 0x2ecc71)
            add_field(embed, "VPS Inventory", chunk, False)
            embed.set_footer(text=f"AxionHost • VPS Information System")
            await ctx.send(embed=embed)
    else:
        found_vps = None
        found_user = None
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    found_vps = vps
                    found_user = await bot.fetch_user(int(user_id))
                    break
            if found_vps:
                break
        if not found_vps:
            await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
            return
        node = get_node(found_vps['node_id'])
        node_name = node['name'] if node else "Unknown"
        
        # Determine status color based on expiration and suspension
        status_color = 0x1a1a1a
        if found_vps.get('suspended', False):
            status_color = 0xffaa00
        elif found_vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(found_vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            if days_remaining < 0:
                status_color = 0xff3366
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                status_color = 0xffaa00
            else:
                status_color = 0x2ecc71
        
        suspended_text = " (SUSPENDED)" if found_vps.get('suspended', False) else ""
        whitelisted_text = " (WHITELISTED)" if found_vps.get('whitelisted', False) else ""
        embed = create_embed(f"🖥️ VPS Information - {container_name}", f"Detailed VPS profile owned by {found_user.mention}{suspended_text}{whitelisted_text}", status_color)
        
        add_field(embed, "👤 Owner", f"**Name:** {found_user.name}\n**ID:** `{found_user.id}`\n**Mention:** {found_user.mention}", False)
        
        add_field(embed, "🌐 Location & Node", f"**Node:** {node_name}\n**Node Type:** {'📍 Local' if node.get('is_local') else '🌐 Remote'}\n**Node ID:** `{found_vps.get('node_id', 1)}`", True)
        
        add_field(embed, "📊 Specifications", f"**RAM:** `{found_vps['ram']}`\n**CPU:** `{found_vps['cpu']}` Cores\n**Storage:** `{found_vps['storage']}`\n**Config:** {found_vps.get('config', 'Custom')}", True)
        
        # Status information
        status_info = f"**Current Status:** `{found_vps.get('status', 'unknown').upper()}`\n"
        status_info += f"**Suspended:** {'🟡 Yes' if found_vps.get('suspended', False) else '🟢 No'}\n"
        status_info += f"**Whitelisted:** {'✅ Yes' if found_vps.get('whitelisted', False) else '❌ No'}\n"
        status_info += f"**Created:** `{found_vps.get('created_at', 'Unknown')}`"
        add_field(embed, "📈 Status", status_info, False)
        
        # Expiration information
        if found_vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(found_vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            
            if days_remaining < 0:
                exp_status = "🔴 EXPIRED"
                exp_color = "FF3366"
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                exp_status = "🟡 EXPIRING SOON"
                exp_color = "FFAA00"
            else:
                exp_status = "🟢 ACTIVE"
                exp_color = "2ECC71"
            
            exp_info = f"**Status:** {exp_status}\n"
            exp_info += f"**Expires On:** `{expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}`\n"
            exp_info += f"**Days Remaining:** `{max(0, days_remaining)}` days\n"
            exp_info += f"**Time Left:** `{max(0, days_remaining)} days` from today"
            add_field(embed, "⏰ Expiration", exp_info, False)
        else:
            add_field(embed, "⏰ Expiration", f"**Status:** 🔵 No expiration date set\n**Action:** Use `{PREFIX}set-expiration` to configure", False)
        
        if found_vps.get('shared_with'):
            shared_users = []
            for shared_id in found_vps['shared_with']:
                try:
                    shared_user = await bot.fetch_user(int(shared_id))
                    shared_users.append(f"• {shared_user.mention} (`{shared_id}`)")
                except:
                    shared_users.append(f"• Unknown User (`{shared_id}`)")
            shared_text = "\n".join(shared_users)
            add_field(embed, "🔗 Shared Access", shared_text, False)
        
        # Port forwarding info
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM port_forwards WHERE vps_container = ?', (container_name,))
        port_count = cur.fetchone()[0]
        cur.execute('SELECT * FROM port_forwards WHERE vps_container = ? LIMIT 5', (container_name,))
        ports = cur.fetchall()
        conn.close()
        
        if port_count > 0:
            port_info = f"**Total:** `{port_count}` forwarded ports (TCP & UDP)\n"
            if ports:
                port_info += "**Active Forwards:**\n"
                for p in ports:
                    port_info += f"  • `{p['host_port']}` → VPS:`{p['vps_port']}`\n"
                if port_count > 5:
                    port_info += f"  • ... +{port_count - 5} more"
            add_field(embed, "🌐 Port Forwarding", port_info, False)
        else:
            add_field(embed, "🌐 Port Forwarding", "**Status:** No active port forwards", False)
        
        # OS information
        add_field(embed, "🐧 Operating System", f"`{found_vps.get('os_version', 'ubuntu:22.04')}`", True)
        
        embed.set_footer(text=f"AxionHost • VPS Information System • Container: {container_name}")
        await ctx.send(embed=embed)

@bot.command(name='restart-vps')
@is_admin()
async def restart_vps(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Restarting VPS", f"Restarting VPS `{container_name}`..."))
    try:
        await execute_lxc(container_name, f"restart {container_name}", node_id=node_id)
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    vps['status'] = 'running'
                    save_vps_data()
                    break
        await apply_internal_permissions(container_name, node_id)
        await recreate_port_forwards(container_name)
        await ctx.send(embed=create_success_embed("VPS Restarted", f"VPS `{container_name}` has been restarted successfully!"))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Restart Failed", f"Error: {str(e)}"))

@bot.command(name='exec')
@is_admin()
async def execute_command(ctx, container_name: str, *, command: str):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Executing Command", f"Running command in VPS `{container_name}`..."))
    try:
        output = await execute_lxc(container_name, f"exec {container_name} -- sh -c \"{command}\"", node_id=node_id)
        embed = create_embed(f"Command Output - {container_name}", f"Command: `{command}`", 0x1a1a1a)
        if output.strip():
            if len(output) > 1000:
                output = output[:1000] + "\n... (truncated)"
            add_field(embed, "📤 Output", f"```\n{output}\n```", False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Execution Failed", f"Error: {str(e)}"))

@bot.command(name='stop-vps-all')
@is_admin()
async def stop_all_vps(ctx):
    embed = create_warning_embed("Stopping All VPS", "⚠️ **WARNING:** This will stop ALL running VPS on all nodes.\n\nThis action cannot be undone. Continue?")
    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="Stop All VPS", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, item: discord.ui.Button):
            await interaction.response.defer()
            try:
                stopped_count = 0
                nodes = get_nodes()
                for node in nodes:
                    if node['is_local']:
                        proc = await asyncio.create_subprocess_exec(
                            LXC_CMD, "stop", "--all", "--force",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        stdout, stderr = await proc.communicate()
                        if proc.returncode != 0:
                            logger.error(f"Failed to stop all on local node: {stderr.decode()}")
                            continue
                    else:
                        url = f"{node['url']}/api/execute"
                        data = {"command": "lxc stop --all --force"}
                        params = {"api_key": node["api_key"]}
                        response = await http_request('POST', url, json=data, params=params, timeout=30)
                        if response.status_code != 200:
                            logger.error(f"Failed to stop all on node {node['name']}")
                            continue
                    for user_id, vps_list in vps_data.items():
                        for vps in vps_list:
                            if vps.get('node_id') == node['id'] and vps.get('status') == 'running':
                                vps['status'] = 'stopped'
                                vps['suspended'] = False
                                stopped_count += 1
                save_vps_data()
                embed = create_success_embed("All VPS Stopped", f"Successfully stopped {stopped_count} VPS across all nodes.")
                await interaction.followup.send(embed=embed)
            except Exception as e:
                embed = create_error_embed("Error", f"Error stopping VPS: {str(e)}")
                await interaction.followup.send(embed=embed)

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, item: discord.ui.Button):
            await interaction.response.edit_message(embed=create_info_embed("Operation Cancelled", "The stop all VPS operation has been cancelled."))

    await ctx.send(embed=embed, view=ConfirmView())

@bot.command(name='cpu-monitor')
@is_admin()
async def resource_monitor_control(ctx, action: str = "status"):
    global resource_monitor_active
    if action.lower() == "status":
        status = "Active" if resource_monitor_active else "Inactive"
        embed = create_embed("Resource Monitor Status", f"Resource monitoring is currently **{status}** (logs only; no auto-stop)", 0x00ccff if resource_monitor_active else 0xffaa00)
        add_field(embed, "Thresholds", f"{CPU_THRESHOLD}% CPU / {RAM_THRESHOLD}% RAM usage", True)
        add_field(embed, "Check Interval", f"60 seconds (all nodes)", True)
        await ctx.send(embed=embed)
    elif action.lower() == "enable":
        resource_monitor_active = True
        await ctx.send(embed=create_success_embed("Resource Monitor Enabled", "Resource monitoring has been enabled."))
    elif action.lower() == "disable":
        resource_monitor_active = False
        await ctx.send(embed=create_warning_embed("Resource Monitor Disabled", "Resource monitoring has been disabled."))
    else:
        await ctx.send(embed=create_error_embed("Invalid Action", f"Use: `{PREFIX}cpu-monitor <status|enable|disable>`"))

@bot.command(name='resize-vps')
@is_admin()
async def resize_vps(ctx, container_name: str, ram: int = None, cpu: int = None, disk: int = None):
    for label, value in (("RAM", ram), ("CPU", cpu), ("Disk", disk)):
        if value is not None and int(value) <= 0:
            await ctx.send(embed=create_error_embed("Invalid Resource Value", f"{label} must be a positive whole number."))
            return
    if ram is None and cpu is None and disk is None:
        await ctx.send(embed=create_error_embed("Missing Parameters", "Please specify at least one resource to resize (ram, cpu, or disk)"))
        return
    found_vps = None
    user_id = None
    vps_index = None
    for uid, vps_list in vps_data.items():
        for i, vps in enumerate(vps_list):
            if vps['container_name'] == container_name:
                found_vps = vps
                user_id = uid
                vps_index = i
                break
        if found_vps:
            break
    if not found_vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
        return
    node_id = found_vps['node_id']
    was_running = found_vps.get('status') == 'running' and not found_vps.get('suspended', False)
    disk_changed = disk is not None
    if disk is not None:
        try:
            current_disk_for_check = int(str(found_vps.get('storage', '0GB')).upper().replace('GB', '').strip())
        except (TypeError, ValueError):
            await ctx.send(embed=create_error_embed('Invalid VPS Metadata', 'Stored disk size is invalid; resource changes were not applied.'))
            return
        if int(disk) < current_disk_for_check:
            await ctx.send(embed=create_error_embed('Disk Shrink Not Supported', f'Current disk is `{current_disk_for_check}GB`. This command supports disk expansion only; shrinking can destroy guest data.'))
            return
    if was_running:
        await ctx.send(embed=create_info_embed("Stopping VPS", f"Stopping VPS `{container_name}` to apply resource changes..."))
        try:
            await execute_lxc(container_name, f"stop {container_name}", node_id=node_id)
            found_vps['status'] = 'stopped'
            save_vps_data()
        except Exception as e:
            await ctx.send(embed=create_error_embed("Stop Failed", f"Error stopping VPS: {str(e)}"))
            return
    changes = []
    try:
        new_ram = int(found_vps['ram'].replace('GB', ''))
        new_cpu = int(found_vps['cpu'])
        new_disk = int(found_vps['storage'].replace('GB', ''))
        if ram is not None and ram > 0:
            new_ram = ram
            ram_mb = ram * 1024
            await execute_lxc(container_name, f"config set {container_name} limits.memory {ram_mb}MB", node_id=node_id)
            changes.append(f"RAM: {ram}GB")
        if cpu is not None and cpu > 0:
            new_cpu = cpu
            await execute_lxc(container_name, f"config set {container_name} limits.cpu {cpu}", node_id=node_id)
            changes.append(f"CPU: {cpu} cores")
        if disk is not None and disk > 0:
            new_disk = disk
            await execute_lxc(container_name, f"config device set {container_name} root size={disk}GB", node_id=node_id)
            changes.append(f"Disk: {disk}GB")
        found_vps['ram'] = f"{new_ram}GB"
        found_vps['cpu'] = str(new_cpu)
        found_vps['storage'] = f"{new_disk}GB"
        found_vps['config'] = f"{new_ram}GB RAM / {new_cpu} CPU / {new_disk}GB Disk"
        vps_data[user_id][vps_index] = found_vps
        save_vps_data()
        if was_running:
            await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
            found_vps['status'] = 'running'
            save_vps_data()
            await apply_internal_permissions(container_name, node_id)
            await recreate_port_forwards(container_name)
        embed = create_success_embed("VPS Resized", f"Successfully resized resources for VPS `{container_name}`")
        add_field(embed, "Changes Applied", "\n".join(changes), False)
        if disk_changed:
            add_field(embed, "Disk Note", "The virtual disk size was updated. Expand the guest partition/filesystem inside the VPS (for example, use `growpart` and `resize2fs` on ext4, or the matching tool for your filesystem).", False)
        await ctx.send(embed=embed)
    except Exception as e:
        if was_running:
            try:
                await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
                found_vps['status'] = 'running'
                save_vps_data_immediate()
            except Exception as restart_error:
                logger.error('Could not restore VPS %s after resize failure: %s', container_name, restart_error)
        await ctx.send(embed=create_error_embed("Resize Failed", f"Error: {str(e)}"))

@bot.command(name='clone-vps')
@is_admin()
async def clone_vps(ctx, container_name: str, new_name: str = None):
    if not new_name:
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        new_name = f"{BOT_NAME.lower()}-{container_name}-clone-{timestamp}"
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Cloning VPS", f"Cloning VPS `{container_name}` to `{new_name}`..."))
    try:
        found_vps = None
        user_id = None
        for uid, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    found_vps = vps
                    user_id = uid
                    break
            if found_vps:
                break
        if not found_vps:
            await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
            return
        await execute_lxc(container_name, f"copy {container_name} {new_name}", node_id=node_id)
        await apply_lxc_config(new_name, node_id)
        await execute_lxc(new_name, f"start {new_name}", node_id=node_id)
        await apply_internal_permissions(new_name, node_id)
        await recreate_port_forwards(new_name)
        if user_id not in vps_data:
            vps_data[user_id] = []
        new_vps = found_vps.copy()
        new_vps['container_name'] = new_name
        new_vps['status'] = 'running'
        new_vps['suspended'] = False
        new_vps['whitelisted'] = False
        new_vps['suspension_history'] = []
        new_vps['created_at'] = datetime.now().isoformat()
        new_vps['shared_with'] = []
        new_vps['id'] = None
        vps_data[user_id].append(new_vps)
        save_vps_data()
        embed = create_success_embed("VPS Cloned", f"Successfully cloned VPS `{container_name}` to `{new_name}`")
        add_field(embed, "New VPS Details", f"**RAM:** {new_vps['ram']}\n**CPU:** {new_vps['cpu']} Cores\n**Storage:** {new_vps['storage']}", False)
        add_field(embed, "Features", "Nesting, Privileged, FUSE, Kernel Modules (Docker Ready), Unprivileged Ports from 0", False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Clone Failed", f"Error: {str(e)}"))

@bot.command(name='migrate-vps')
@is_admin()
async def migrate_vps(ctx, container_name: str, target_node_id: int):
    node_id = find_node_id_for_container(container_name)
    target_node = get_node(target_node_id)
    if not target_node:
        await ctx.send(embed=create_error_embed("Invalid Node", "Target node not found."))
        return
    await ctx.send(embed=create_info_embed("Migrating VPS", f"Migrating VPS `{container_name}` to node {target_node['name']}..."))
    try:
        await execute_lxc(container_name, f"stop {container_name}", node_id=node_id)
        temp_name = f"{BOT_NAME.lower()}-{container_name}-temp-{int(time.time())}"
        await execute_lxc(container_name, f"copy {container_name} {temp_name} -s {DEFAULT_STORAGE_POOL}", node_id=target_node_id)
        await execute_lxc(container_name, f"delete {container_name} --force", node_id=node_id)
        await execute_lxc(temp_name, f"rename {temp_name} {container_name}", node_id=target_node_id)
        await apply_lxc_config(container_name, target_node_id)
        await execute_lxc(container_name, f"start {container_name}", node_id=target_node_id)
        await apply_internal_permissions(container_name, target_node_id)
        await recreate_port_forwards(container_name)
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    vps['node_id'] = target_node_id
                    vps['status'] = 'running'
                    vps['suspended'] = False
                    save_vps_data()
                    break
        await ctx.send(embed=create_success_embed("VPS Migrated", f"Successfully migrated VPS `{container_name}` to node {target_node['name']}"))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Migration Failed", f"Error: {str(e)}"))

@bot.command(name='vps-stats')
@is_admin()
async def vps_stats(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Gathering Statistics", f"Collecting statistics for VPS `{container_name}`..."))
    try:
        stats = await get_container_stats(container_name, node_id)
        embed = create_embed(f"📊 VPS Statistics - {container_name}", f"Resource usage statistics", 0x1a1a1a)
        add_field(embed, "📈 Status", f"**{stats['status'].upper()}**", False)
        add_field(embed, "💻 CPU Usage", f"**{stats['cpu']:.1f}%**", True)
        add_field(embed, "🧠 Memory Usage", f"**{stats['ram']['used']}/{stats['ram']['total']} MB ({stats['ram']['pct']:.1f}%)**", True)
        add_field(embed, "💾 Disk Usage", f"**{stats['disk']}**", True)
        add_field(embed, "⏱️ Uptime", f"**{stats['uptime']}**", True)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Statistics Failed", f"Error: {str(e)}"))


@bot.command(name='node-check')
@is_admin()
async def node_check(ctx, node_id: int):
    """Check node status and available storage pools"""
    node = get_node(node_id)
    if not node:
        await ctx.send(embed=create_error_embed("Node Not Found", f"Node ID {node_id} not found."))
        return
    
    embed = create_info_embed(f"Node Check - {node['name']}", 
                             f"Checking status and configuration of node {node['name']}...")
    
    # Check if node is reachable
    status = await get_node_status(node_id)
    add_field(embed, "📡 Connection Status", status, False)
    
    if status.startswith("🟢"):
        # Try to get storage pools
        try:
            pools_output = await execute_lxc("", "storage list", node_id=node_id, timeout=30)
            add_field(embed, "💾 Available Storage Pools", f"```{pools_output}```", False)
            
            # Try to get default profile
            try:
                profile_output = await execute_lxc("", "profile list", node_id=node_id, timeout=30)
                add_field(embed, "📋 Available Profiles", f"```{profile_output[:500]}...```", False)
            except Exception as e:
                add_field(embed, "📋 Profiles", f"Error: {str(e)[:200]}", False)
                
        except Exception as e:
            add_field(embed, "💾 Storage Pools", f"Error: {str(e)[:200]}", False)
        
        # Check remote API endpoint
        try:
            test_response = await http_request('GET', f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
            add_field(embed, "🔌 API Endpoint", f"✅ Reachable\nURL: {node['url']}", False)
        except Exception as e:
            add_field(embed, "🔌 API Endpoint", f"❌ Unreachable\nError: {str(e)[:200]}", False)
    else:
        add_field(embed, "⚠️ Status", "Node is offline or unreachable", False)
    
    await ctx.send(embed=embed)

@bot.command(name='vps-network')
@is_admin()
async def vps_network(ctx, container_name: str, action: str, value: str = None):
    node_id = find_node_id_for_container(container_name)
    if action.lower() not in ["list", "add", "remove", "limit"]:
        await ctx.send(embed=create_error_embed("Invalid Action", f"Use: `{PREFIX}vps-network <container> <list|add|remove|limit> [value]`"))
        return
    try:
        if action.lower() == "list":
            output = await execute_lxc(container_name, f"exec {container_name} -- ip addr", node_id=node_id)
            if len(output) > 1000:
                output = output[:1000] + "\n... (truncated)"
            embed = create_embed(f"🌐 Network Interfaces - {container_name}", "Network configuration", 0x1a1a1a)
            add_field(embed, "Interfaces", f"```\n{output}\n```", False)
            await ctx.send(embed=embed)
        elif action.lower() == "limit" and value:
            await execute_lxc(container_name, f"config device set {container_name} eth0 limits.egress {value}", node_id=node_id)
            await execute_lxc(container_name, f"config device set {container_name} eth0 limits.ingress {value}", node_id=node_id)
            await ctx.send(embed=create_success_embed("Network Limited", f"Set network limit to {value} for `{container_name}`"))
        elif action.lower() == "add" and value:
            await execute_lxc(container_name, f"config device add {container_name} eth1 nic nictype=bridged parent={value}", node_id=node_id)
            await ctx.send(embed=create_success_embed("Network Added", f"Added network interface to VPS `{container_name}` with bridge `{value}`"))
        elif action.lower() == "remove" and value:
            await execute_lxc(container_name, f"config device remove {container_name} {value}", node_id=node_id)
            await ctx.send(embed=create_success_embed("Network Removed", f"Removed network interface `{value}` from VPS `{container_name}`"))
        else:
            await ctx.send(embed=create_error_embed("Invalid Parameters", "Please provide valid parameters for the action"))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Network Management Failed", f"Error: {str(e)}"))

@bot.command(name='vps-processes')
@is_admin()
async def vps_processes(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Gathering Processes", f"Listing processes in VPS `{container_name}`..."))
    try:
        output = await execute_lxc(container_name, f"exec {container_name} -- ps aux", node_id=node_id)
        if len(output) > 1000:
            output = output[:1000] + "\n... (truncated)"
        embed = create_embed(f"⚙️ Processes - {container_name}", "Running processes", 0x1a1a1a)
        add_field(embed, "Process List", f"```\n{output}\n```", False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Process Listing Failed", f"Error: {str(e)}"))

@bot.command(name='vps-logs')
@is_admin()
async def vps_logs(ctx, container_name: str, lines: int = 50):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Gathering Logs", f"Fetching last {lines} lines from VPS `{container_name}`..."))
    try:
        output = await execute_lxc(container_name, f"exec {container_name} -- journalctl -n {lines}", node_id=node_id)
        if len(output) > 1000:
            output = output[:1000] + "\n... (truncated)"
        embed = create_embed(f"📋 Logs - {container_name}", f"Last {lines} log lines", 0x1a1a1a)
        add_field(embed, "System Logs", f"```\n{output}\n```", False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Log Retrieval Failed", f"Error: {str(e)}"))

@bot.command(name='vps-uptime')
@is_admin()
async def vps_uptime(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    uptime = await get_container_uptime(container_name, node_id)
    embed = create_info_embed("VPS Uptime", f"Uptime for `{container_name}`: {uptime}")
    await ctx.send(embed=embed)

@bot.command(name='vps-password')
@is_admin()
async def vps_password(ctx, container_name: str = None):
    """View or manage VPS root passwords"""
    if not container_name:
        # Show all passwords for all VPS
        password_list = []
        for user_id, vps_list in vps_data.items():
            try:
                user = await bot.fetch_user(int(user_id))
                for vps in vps_list:
                    password = vps.get('root_password', 'Not Set')
                    if password == 'Not Set':
                        password_display = "❌ Not Set"
                    else:
                        password_display = f"🔐 `{password}`"
                    password_list.append(f"**{user.name}** - `{vps['container_name']}`: {password_display}")
            except:
                pass
        
        if not password_list:
            await ctx.send(embed=create_info_embed("No Passwords", "No VPS passwords found in database."))
            return
        
        password_text = "\n".join(password_list)
        chunks = [password_text[i:i+1024] for i in range(0, len(password_text), 1024)]
        for idx, chunk in enumerate(chunks, 1):
            embed = create_embed(f"🔐 VPS Root Passwords (Part {idx}/{len(chunks)})", "Root passwords for all VPS", 0xff6b6b)
            add_field(embed, "Passwords", chunk, False)
            add_field(embed, "⚠️ Security Notice", "These passwords are sensitive. Do not share them publicly.", False)
            embed.set_footer(text=f"AxionHost • Password Management")
            await ctx.send(embed=embed)
    else:
        # Show password for specific VPS
        found_vps = None
        found_user = None
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    found_vps = vps
                    found_user = await bot.fetch_user(int(user_id))
                    break
            if found_vps:
                break
        
        if not found_vps:
            await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
            return
        
        password = found_vps.get('root_password', 'Not Set')
        if password == 'Not Set':
            embed = create_info_embed("Password Not Set", f"VPS `{container_name}` does not have a stored password.")
        else:
            embed = create_success_embed("VPS Password", f"Root password for VPS `{container_name}`")
            add_field(embed, "Owner", f"{found_user.mention}", True)
            add_field(embed, "Container", f"`{container_name}`", True)
            add_field(embed, "🔐 Password", f"`{password}`", False)
            add_field(embed, "Usage", f"SSH as `root` with this password", False)
        
        embed.set_footer(text=f"AxionHost • Password Information")
        await ctx.send(embed=embed)

@bot.command(name='suspend-vps')
@is_admin()
async def suspend_vps(ctx, container_name: str, *, reason: str = "Admin action"):
    node_id = find_node_id_for_container(container_name)
    found = False
    for uid, lst in vps_data.items():
        for vps in lst:
            if vps['container_name'] == container_name:
                if vps.get('status') != 'running':
                    await ctx.send(embed=create_error_embed("Cannot Suspend", "VPS must be running to suspend."))
                    return
                try:
                    await execute_lxc(container_name, f"stop {container_name}", node_id=node_id)
                    vps['status'] = 'stopped'
                    vps['suspended'] = True
                    if 'suspension_history' not in vps:
                        vps['suspension_history'] = []
                    vps['suspension_history'].append({
                        'time': datetime.now().isoformat(),
                        'reason': reason,
                        'by': f"{ctx.author.name} ({ctx.author.id})"
                    })
                    save_vps_data()
                except Exception as e:
                    await ctx.send(embed=create_error_embed("Suspend Failed", str(e)))
                    return
                try:
                    owner = await bot.fetch_user(int(uid))
                    embed = create_warning_embed("🚨 VPS Suspended", f"Your VPS `{container_name}` has been suspended by an admin.\n\n**Reason:** {reason}\n\nContact an admin to unsuspend.")
                    await owner.send(embed=embed)
                except Exception as dm_e:
                    logger.error(f"Failed to DM owner {uid}: {dm_e}")
                await ctx.send(embed=create_success_embed("VPS Suspended", f"VPS `{container_name}` suspended. Reason: {reason}"))
                found = True
                break
        if found:
            break
    if not found:
        await ctx.send(embed=create_error_embed("Not Found", f"VPS `{container_name}` not found."))

@bot.command(name='unsuspend-vps')
@is_admin()
async def unsuspend_vps(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    found = False
    for uid, lst in vps_data.items():
        for vps in lst:
            if vps['container_name'] == container_name:
                if not vps.get('suspended', False):
                    await ctx.send(embed=create_error_embed("Not Suspended", "VPS is not suspended."))
                    return
                try:
                    vps['suspended'] = False
                    vps['status'] = 'running'
                    await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
                    await apply_internal_permissions(container_name, node_id)
                    await recreate_port_forwards(container_name)
                    save_vps_data()
                    await ctx.send(embed=create_success_embed("VPS Unsuspended", f"VPS `{container_name}` unsuspended and started."))
                    found = True
                except Exception as e:
                    await ctx.send(embed=create_error_embed("Start Failed", str(e)))
                try:
                    owner = await bot.fetch_user(int(uid))
                    embed = create_success_embed("🟢 VPS Unsuspended", f"Your VPS `{container_name}` has been unsuspended by an admin.\nYou can now manage it again.")
                    await owner.send(embed=embed)
                except Exception as dm_e:
                    logger.error(f"Failed to DM owner {uid} about unsuspension: {dm_e}")
                break
        if found:
            break
    if not found:
        await ctx.send(embed=create_error_embed("Not Found", f"VPS `{container_name}` not found."))

@bot.command(name='suspension-logs')
@is_admin()
async def suspension_logs(ctx, container_name: str = None):
    if container_name:
        found = None
        for lst in vps_data.values():
            for vps in lst:
                if vps['container_name'] == container_name:
                    found = vps
                    break
            if found:
                break
        if not found:
            await ctx.send(embed=create_error_embed("Not Found", f"VPS `{container_name}` not found."))
            return
        history = found.get('suspension_history', [])
        if not history:
            await ctx.send(embed=create_info_embed("No Suspensions", f"No suspension history for `{container_name}`."))
            return
        embed = create_embed("Suspension History", f"For `{container_name}`")
        text = []
        for h in sorted(history, key=lambda x: x['time'], reverse=True)[:10]:
            t = datetime.fromisoformat(h['time']).strftime('%Y-%m-%d %H:%M:%S')
            text.append(f"**{t}** - {h['reason']} (by {h['by']})")
        add_field(embed, "History", "\n".join(text), False)
        if len(history) > 10:
            add_field(embed, "Note", "Showing last 10 entries.")
        await ctx.send(embed=embed)
    else:
        all_logs = []
        for uid, lst in vps_data.items():
            for vps in lst:
                h = vps.get('suspension_history', [])
                for event in sorted(h, key=lambda x: x['time'], reverse=True):
                    t = datetime.fromisoformat(event['time']).strftime('%Y-%m-%d %H:%M')
                    all_logs.append(f"**{t}** - VPS `{vps['container_name']}` (Owner: <@{uid}>) - {event['reason']} (by {event['by']})")
        if not all_logs:
            await ctx.send(embed=create_info_embed("No Suspensions", "No suspension events recorded."))
            return
        logs_text = "\n".join(all_logs)
        chunks = [logs_text[i:i+1024] for i in range(0, len(logs_text), 1024)]
        for idx, chunk in enumerate(chunks, 1):
            embed = create_embed(f"Suspension Logs (Part {idx})", f"Global suspension events (newest first)")
            add_field(embed, "Events", chunk, False)
            await ctx.send(embed=embed)

@bot.command(name='apply-permissions')
@is_admin()
async def apply_permissions(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Applying Permissions", f"Applying advanced permissions to `{container_name}`..."))
    try:
        status = await get_container_status(container_name, node_id)
        was_running = status == 'running'
        if was_running:
            await execute_lxc(container_name, f"stop {container_name}", node_id=node_id)
        await apply_lxc_config(container_name, node_id)
        await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
        await apply_internal_permissions(container_name, node_id)
        await recreate_port_forwards(container_name)
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    vps['status'] = 'running'
                    vps['suspended'] = False
                    save_vps_data()
                    break
        await ctx.send(embed=create_success_embed("Permissions Applied", f"Advanced permissions applied to VPS `{container_name}`. Docker-ready with unprivileged ports!"))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Apply Failed", f"Error: {str(e)}"))

@bot.command(name='docker-fix')
@is_admin()
async def docker_fix(ctx, vps_id: int):
    """Prepare an existing LXC VPS for nested Docker and diagnose runc/AppArmor compatibility."""
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("Not Found", f"VPS ID `{vps_id}` not found."))
        return
    container_name = vps['container_name']
    node_id = int(vps.get('node_id', 1))
    if get_vps_backend(container_name) != 'lxc':
        await ctx.send(embed=create_error_embed("Docker Fix", "Nested Docker preparation is only for LXC VPS. KVM already provides a VM boundary."))
        return
    await ctx.send(embed=create_info_embed("🐳 Docker Fix", f"Preparing `{container_name}` for nested Docker..."))
    try:
        was_running = (await get_container_status(container_name, node_id)) == 'running'
        if was_running:
            await execute_lxc(container_name, f"stop {container_name}", node_id=node_id)
        # Apply the documented Incus nesting configuration plus common Docker kernel modules.
        await execute_lxc(container_name, f"config set {container_name} security.nesting true", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} security.syscalls.intercept.mknod true", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} security.syscalls.intercept.setxattr true", node_id=node_id)
        if VPS_DOCKER_KERNEL_MODULES:
            await execute_lxc(container_name, f"config set {container_name} linux.kernel_modules {shlex.quote(VPS_DOCKER_KERNEL_MODULES)}", node_id=node_id)
        await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
        await asyncio.sleep(3)
        for uid, items in vps_data.items():
            for item in items:
                if item.get('container_name') == container_name:
                    item['docker_ready'] = True
                    item['status'] = 'running'
        save_vps_data_immediate()
        diag = await execute_lxc(container_name, f"exec {container_name} -- sh -c 'docker --version 2>/dev/null || true; runc --version 2>/dev/null | head -n1 || true; cat /etc/os-release | head -n2'", node_id=node_id)
        host_diag = await _run_local_process([LXC_CMD, 'version'], timeout=15, check=False) if shutil.which(LXC_CMD) else ''
        text = "Docker nesting is enabled.\n\nGuest:\n" + str(diag)[:900]
        text += "\n\nHost runtime:\n" + str(host_diag)[:500]
        text += "\n\n⚠️ If `docker run` still fails with `net.ipv4.ip_unprivileged_port_start`, update the host Incus/LXC/AppArmor stack. This exact failure is associated with newer runc and older generated AppArmor rules; changing the guest sysctl alone does not fix it."
        await ctx.send(embed=create_success_embed("🐳 Docker Ready / Diagnostic", text))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Docker Fix Failed", str(e)))

@bot.command(name='vps-network-test')
async def vps_network_test(ctx, vps_id: int):
    """Show KVM/LXC network state and actionable connectivity diagnostics."""
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("Not Found", f"VPS ID `{vps_id}` not found."))
        return
    owner_id = str(vps.get('user_id'))
    if str(ctx.author.id) != owner_id and not is_admin_user_id(str(ctx.author.id)):
        await ctx.send(embed=create_error_embed("Access Denied", "You do not own this VPS."))
        return
    backend = vps.get('backend', 'lxc')
    try:
        if backend == 'kvm':
            nets = await get_kvm_networks(vps['container_name'])
            netinfo = await _run_local_process(['virsh', 'net-info', KVM_NETWORK], timeout=15, check=False)
            embed = create_info_embed("🌐 KVM Network Test", f"`{vps['container_name']}`")
            add_field(embed, "IP addresses", '\n'.join(f"`{k}` → `{v}`" for k,v in nets.items()) or 'No lease reported yet', False)
            add_field(embed, "libvirt network", f"`{KVM_NETWORK}`\n```{netinfo[:700]}```", False)
            ip = next(iter(nets.values()), None)
            add_field(embed, "SSH", f"`ssh root@{ip or '<wait-for-IP>'}`", False)
            if ip and (ip.startswith('10.') or ip.startswith('192.168.') or re.match(r'^172\.(1[6-9]|2[0-9]|3[0-1])\.', ip)):
                add_field(embed, "IPv4 Type", "Private/NAT IPv4. Outbound internet can work, but the address is not directly reachable from the public internet.", False)
            try:
                diag = await kvm_guest_network_doctor(vps['container_name'], repair=False)
                add_field(embed, "Guest Internet", f"DNS `{diag.get('dns','UNKNOWN')}` • IPv4 `{diag.get('addr4','missing')}` • HTTPS `{diag.get('https','UNKNOWN')}`", False)
            except Exception as exc:
                add_field(embed, "Guest Agent", f"`{str(exc)[:500]}`", False)
            await ctx.send(embed=embed)
        else:
            nets = await get_container_networks(vps['container_name'], int(vps.get('node_id', 1)))
            embed = create_info_embed("🌐 LXC Network Test", f"`{vps['container_name']}`")
            add_field(embed, "Interfaces", '\n'.join(f"`{k}` → `{v}`" for k,v in nets.items()) or 'No IP reported', False)
            await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Network Test Failed", str(e)))

@bot.command(name='kvm-repair')
@is_admin()
async def kvm_repair(ctx):
    """Repair local KVM/libvirt prerequisites."""
    try:
        await ctx.send(embed=create_info_embed('🛠️🔧 KVM Host Repair', 'Installing/checking KVM, QEMU, libvirt and kernel modules…'))
        result = await _ensure_kvm_host_ready(auto_install=True)
        caps = result['caps']
        lines = [f"virsh: {'✅' if caps.get('virsh') else '❌'}", f"virt-install: {'✅' if caps.get('virt_install') else '❌'}", f"qemu-img: {'✅' if caps.get('qemu_img') else '❌'}", f"/dev/kvm: {'✅' if caps.get('kvm_device') else '❌'}", f"Ready: {'✅ YES' if result.get('ready') else '❌ NO'}"]
        if result.get('actions'): lines.append('Actions: ' + '; '.join(result['actions']))
        if result.get('error'): lines.append('⚠️ ' + result['error'])
        embed = create_success_embed('✅ KVM Host Ready', '\n'.join(lines)) if result.get('ready') else create_error_embed('⚠️ KVM Host Still Not Ready', '\n'.join(lines))
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed('KVM Repair Failed', str(e)))

@bot.command(name='kvm-network-repair')
@is_admin()
async def kvm_network_repair(ctx, vps_ref: str = None):
    """Repair/check IPv4 DHCP and outbound internet for a KVM guest."""
    if not vps_ref:
        await ctx.send(embed=create_error_embed('Missing VPS', f'Usage: `{PREFIX}kvm-network-repair <VPS ID or name>`'))
        return
    vps = resolve_vps_reference(vps_ref)
    if not vps or str(vps.get('backend', 'lxc')).lower() != 'kvm':
        await ctx.send(embed=create_error_embed('KVM VPS Not Found', 'Provide a valid KVM VPS ID or container name.'))
        return
    name = vps['container_name']
    try:
        await ctx.send(embed=create_info_embed('🌐🩺 KVM Network Doctor', f'Repairing IPv4/DHCP and checking outbound internet for `{name}`…'))
        host = await ensure_kvm_network()
        before = await kvm_guest_network_doctor(name, repair=False)
        after = before
        if not before.get('ok'):
            after = await kvm_guest_network_doctor(name, repair=True)
        nets = await wait_for_kvm_network(name, timeout=25)
        vps['networks'] = nets
        vps['ipv4'] = next(iter(nets.values()), None)
        vps['network_mode'] = host.get('forward_mode')
        save_vps_data_immediate()
        lines = [f"libvirt network: `{KVM_NETWORK}` / `{host.get('forward_mode')}`", f"IPv4: `{vps.get('ipv4') or 'NOT DETECTED'}`", f"Guest HTTPS: `{'OK' if after.get('https') == 'OK' else 'FAIL'}`", f"Guest DNS: `{'OK' if after.get('dns') == 'OK' else 'FAIL'}`"]
        if after.get('error'): lines.append(f"Agent: `{after['error'][:700]}`")
        if vps.get('ipv4') and (vps['ipv4'].startswith(('192.168.', '10.')) or re.match(r'^172\.(1[6-9]|2[0-9]|3[0-1])\.', vps['ipv4'])):
            lines.append('ℹ️ This is a private NAT IPv4. It can provide outbound internet but is not directly reachable from the public internet. Use SSHX/Pinggy or a routed/bridged public network for inbound access.')
        await ctx.send(embed=create_success_embed('✅ KVM Network Repair Complete', '\n'.join(lines)))
    except Exception as exc:
        await ctx.send(embed=create_error_embed('🚨 KVM Network Repair Failed', str(exc)[:1800]))


@bot.command(name='kvm-cpu-check')
@is_admin()
async def kvm_cpu_check(ctx, model: str = None):
    """Show host-compatible KVM CPU models and optionally validate one exact model."""
    try:
        caps = await get_kvm_cpu_capabilities()
        usable = sorted([name for name, info in caps.get('models', {}).items() if info.get('usable')])
        embed = create_info_embed('🧠 KVM CPU Compatibility', 'Host-specific libvirt CPU capability check')
        add_field(embed, 'Host vendor', f"`{caps.get('host_vendor') or 'Unknown'}`", True)
        add_field(embed, 'Usable named models', f"`{len(usable)}`", True)
        add_field(embed, 'Dynamic modes', f"host-model `{caps.get('host-model', False)}`\nhost-passthrough `{caps.get('host-passthrough', False)}`\nmaximum `{caps.get('maximum', False)}`", True)
        if model:
            result = await check_kvm_cpu_model_compatibility(model)
            status = '✅ COMPATIBLE' if result.get('compatible') else '❌ INCOMPATIBLE'
            detail = f"{status} — `{result.get('model', model)}`\n{result.get('reason', '')}"
            if result.get('blockers'):
                detail += '\nBlockers: `' + ', '.join(result['blockers']) + '`'
            add_field(embed, f'Check: {model[:70]}', detail[:1000], False)
        if usable:
            amd = [m for m in usable if classify_kvm_cpu_model(m) == 'amd'][:10]
            intel = [m for m in usable if classify_kvm_cpu_model(m) == 'intel'][:10]
            if amd: add_field(embed, 'Usable AMD examples', ', '.join(f'`{m}`' for m in amd), False)
            if intel: add_field(embed, 'Usable Intel examples', ', '.join(f'`{m}`' for m in intel), False)
        add_field(embed, 'Why this matters', 'The old CPU picker used QEMU-known models, which can include models the actual host cannot provide. This check uses libvirt host-specific usability/blockers before provisioning.', False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed('KVM CPU Check Failed', str(e)))


@bot.command(name='kvm-selftest')
@is_admin()
async def kvm_selftest(ctx):
    """Run a non-destructive KVM/libvirt readiness test."""
    try:
        caps = _kvm_local_capabilities()
        checks = []
        for key in ('virsh','virt_install','qemu_img','kvm_device'):
            checks.append(f"{key}: {'✅' if caps.get(key) else '❌'}")
        if shutil.which('virsh'):
            net = await _run_local_process(['virsh','net-info',KVM_NETWORK], timeout=15, check=False)
            checks.append(f"network `{KVM_NETWORK}`: {'✅' if net else '❌'}")
            cpu_models = await get_kvm_cpu_models()
            checks.append(f"QEMU CPU models detected: **{len(cpu_models)}**")
            domcap = await _run_local_process(['virsh','capabilities'], timeout=20, check=False)
            kvm_domain_supported = '<domain type="kvm"' in domcap.lower()
            capability_status = '✅' if kvm_domain_supported else '⚠️ not confirmed'
            checks.append(f"libvirt capabilities: {capability_status}")
        checks.append(f"KVM images configured: **{len(KVM_SUPPORTED_IMAGES)}**")
        embed=create_info_embed('🧪 KVM Self-Test','Non-destructive host readiness check')
        add_field(embed,'Checks','\n'.join(checks),False)
        add_field(embed,'Note','This checks the host prerequisites and libvirt configuration; it does not create a real VM. A real provisioning test must run on the target KVM node.',False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed('KVM Self-Test Failed',str(e)))

@bot.command(name='lxc-instance-find')
@is_admin()
async def lxc_instance_find_cmd(ctx, instance_name: str = None):
    """Find an LXC/Incus instance across projects without changing it."""
    if not instance_name:
        await ctx.send(embed=create_error_embed('🔎 Missing Instance Name', f'Usage: `{PREFIX}lxc-instance-find <instance-name>`'))
        return
    try:
        project = await _lxc_find_instance_project(instance_name)
        if project is None:
            raw = await _run_local_process([LXC_CMD, 'list', '--all-projects', '--format=table'], timeout=20, check=False)
            await ctx.send(embed=create_error_embed('❌ Instance Not Found', f'`{instance_name}` was not found in visible projects.\n\n```text\n{raw[:2500]}\n```'))
            return
        raw = await _run_local_process([LXC_CMD, '--project', project, 'info', instance_name], timeout=20, check=False)
        await ctx.send(embed=create_success_embed('✅ Instance Located', f'**Name:** `{instance_name}`\n**Project:** `{project}`\n\n```text\n{raw[:3000]}\n```'))
    except Exception as exc:
        await ctx.send(embed=create_error_embed('🚨 Instance Lookup Failed', str(exc)[:1500]))


@bot.command(name='kvm-qga-check')
@is_admin()
async def kvm_qga_check_cmd(ctx, vm_name: str = None):
    """Check KVM state, DHCP/IP and QEMU Guest Agent separately."""
    if not vm_name:
        await ctx.send(embed=create_error_embed('🔎 Missing VM Name', f'Usage: `{PREFIX}kvm-qga-check <vm-name>`'))
        return
    try:
        state = await _run_local_process(['virsh', '-c', 'qemu:///system', 'domstate', vm_name], timeout=12, check=False)
        interfaces = await _run_local_process(['virsh', '-c', 'qemu:///system', 'domiflist', vm_name], timeout=12, check=False)
        addresses = await get_kvm_networks(vm_name)
        qga = await ensure_kvm_guest_agent_channel(vm_name)
        channel = await _run_local_process(['virsh', '-c', 'qemu:///system', 'dumpxml', vm_name], timeout=15, check=False)
        has_channel = 'org.qemu.guest_agent.0' in channel
        lines = [f'🖥️ VM state: `{state or "UNKNOWN"}`', f'🌐 DHCP/IP: `{", ".join(addresses.values()) if addresses else "NOT DETECTED"}`', f'🧩 Guest-agent channel in XML: `{"YES" if has_channel else "NO"}`', f'🤖 Guest-agent ping: `{"CONNECTED" if qga else "OFFLINE"}`']
        if interfaces:
            lines.append('**NICs**\n```text\n' + interfaces[:900] + '\n```')
        lines.append('ℹ️ A DHCP lease can exist even while QEMU Guest Agent is offline. QGA is needed for in-guest repair, not for detecting a host-side DHCP lease.')
        embed = create_success_embed('🩺 KVM Guest-Agent Diagnostics', '\n'.join(lines)) if qga else create_info_embed('🩺 KVM Guest-Agent Diagnostics', '\n'.join(lines))
        await ctx.send(embed=embed)
    except Exception as exc:
        await ctx.send(embed=create_error_embed('🚨 KVM Diagnostic Failed', str(exc)[:1500]))


async def guest_health_report(vps: Dict[str, Any]) -> Dict[str, Any]:
    """Read-only, bounded guest health report used by diagnostics/repair UX."""
    name = vps['container_name']
    node_id = int(vps.get('node_id', 1))
    backend = str(vps.get('backend', 'lxc')).lower()
    result: Dict[str, Any] = {'backend': backend, 'checks': []}
    if backend == 'kvm':
        nets = await get_kvm_networks(name)
        result['network'] = nets
        result['checks'].append(('VM network', bool(nets), ', '.join(nets.values()) if nets else 'No DHCP/guest-agent IP'))
        dom = await _run_local_process(['virsh', 'dominfo', name], timeout=15, check=False) if shutil.which('virsh') else ''
        result['checks'].append(('libvirt domain', bool(dom), 'domain found' if dom else 'domain not found'))
        try:
            diag = await kvm_guest_network_doctor(name, repair=False)
            result['checks'].append(('Guest IPv4', bool(diag.get('addr4')), diag.get('addr4', 'missing')))
            result['checks'].append(('Guest DNS', diag.get('dns') == 'OK', diag.get('dns', 'UNKNOWN')))
            result['checks'].append(('Guest internet', diag.get('https') == 'OK', diag.get('https', 'UNKNOWN')))
            result['raw'] = diag.get('raw', '')
        except Exception as exc:
            result['checks'].append(('Guest agent', False, str(exc)[:500]))
        return result
    cmd = r'''set +e
printf 'OS='; . /etc/os-release 2>/dev/null && printf '%s\n' "${PRETTY_NAME:-Unknown}" || echo Unknown
printf 'UPTIME='; uptime -p 2>/dev/null || uptime 2>/dev/null || true
printf 'SSH='; pgrep -x sshd >/dev/null 2>&1 && echo RUNNING || (pgrep -x dropbear >/dev/null 2>&1 && echo DROPBEAR || echo STOPPED)
printf 'SSH_CONFIG='; sshd -t >/dev/null 2>&1 && echo OK || echo BAD
printf 'DNS='; getent hosts cloudflare.com >/dev/null 2>&1 && echo OK || echo FAIL
printf 'HTTPS='; curl -fsS --max-time 8 https://www.cloudflare.com/cdn-cgi/trace >/dev/null 2>&1 && echo OK || echo FAIL
printf 'DISK='; df -P / 2>/dev/null | awk 'NR==2{print $5}'
printf 'RAM='; free -m 2>/dev/null | awk '/^Mem:/{print $3 "/" $2 "MB"}'
printf 'DOCKER='; command -v docker >/dev/null 2>&1 && (docker info >/dev/null 2>&1 && echo RUNNING || echo INSTALLED_NOT_RUNNING) || echo NOT_INSTALLED
printf 'CLOUDFLARED='; systemctl is-active cloudflared 2>/dev/null || echo NOT_ACTIVE
printf 'SSHX='; command -v sshx >/dev/null 2>&1 && echo INSTALLED || echo NOT_INSTALLED
printf 'PINGGY='; pgrep -af 'tcp@free.pinggy.io' >/dev/null 2>&1 && echo RUNNING || echo NOT_RUNNING
'''
    raw = await _guest_exec_lxc(name, node_id, cmd, timeout=35)
    result['raw'] = raw[-5000:] if isinstance(raw, str) else str(raw)
    for line in result['raw'].splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            result[k.lower()] = v.strip()
    result['network'] = await get_container_networks(name, node_id)
    result['checks'] = [
        ('Guest network', bool(result['network']), ', '.join(result['network'].values()) if result['network'] else 'No IP detected'),
        ('DNS', result.get('dns') == 'OK', result.get('dns', 'UNKNOWN')),
        ('HTTPS', result.get('https') == 'OK', result.get('https', 'UNKNOWN')),
        ('SSH daemon', result.get('ssh') in ('RUNNING', 'DROPBEAR'), result.get('ssh', 'UNKNOWN')),
        ('SSH config', result.get('ssh_config') == 'OK', result.get('ssh_config', 'UNKNOWN')),
        ('Disk', True, result.get('disk', 'UNKNOWN')),
        ('RAM', True, result.get('ram', 'UNKNOWN')),
        ('Cloudflared', result.get('cloudflared') == 'active', result.get('cloudflared', 'UNKNOWN')),
        ('SSHX', result.get('sshx') == 'INSTALLED', result.get('sshx', 'UNKNOWN')),
        ('Pinggy', result.get('pinggy') == 'RUNNING', result.get('pinggy', 'UNKNOWN')),
    ]
    return result

@bot.command(name='vps-diagnostics')
async def vps_diagnostics(ctx, vps_ref: str = None):
    """Run a bounded read-only guest health report."""
    if not vps_ref:
        await ctx.send(embed=create_error_embed('Missing VPS', f'Usage: `{PREFIX}vps-diagnostics <VPS ID or container-name>`'))
        return
    vps = resolve_vps_reference(vps_ref)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'No VPS matches `{vps_ref}`.'))
        return
    owner_id = str(vps.get('user_id'))
    if str(ctx.author.id) != owner_id and not is_admin_user_id(str(ctx.author.id)):
        await ctx.send(embed=create_error_embed('Access Denied', 'You do not own this VPS.'))
        return
    try:
        report = await guest_health_report(vps)
        embed = create_info_embed('🩺 VPS Diagnostics', f"Full read-only health report for `{vps['container_name']}`")
        add_field(embed, 'Backend / Status', f"`{str(report.get('backend')).upper()}` / `{str(vps.get('status','unknown')).upper()}`", True)
        add_field(embed, 'Network', ', '.join(f'`{k}` → `{v}`' for k,v in report.get('network', {}).items()) or 'No IP detected', False)
        lines=[]
        for label, ok, detail in report.get('checks', []):
            lines.append(f"{'✅' if ok else '⚠️'} **{label}:** {detail}")
        add_field(embed, 'Guest Health', '\n'.join(lines)[:4000] or 'No checks returned.', False)
        if report.get('raw'):
            add_field(embed, 'Raw Guest Output', f"```text\n{report['raw'][-1800:]}\n```", False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed('Diagnostics Failed', str(e)[:1800]))


@bot.command(name='vps-repair')
async def vps_repair(ctx, vps_ref: str = None, component: str = 'all'):
    """Repair common guest-side VPS issues without changing host isolation."""
    if not vps_ref:
        await ctx.send(embed=create_error_embed('Missing VPS', f'Usage: `{PREFIX}vps-repair <VPS ID or container-name> [all|ssh|cloudflare|sshx|docker]`'))
        return
    vps = resolve_vps_reference(vps_ref)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'No VPS matches `{vps_ref}`.'))
        return
    if str(ctx.author.id) != str(vps.get('user_id')) and not is_admin_user_id(str(ctx.author.id)):
        await ctx.send(embed=create_error_embed('Access Denied', 'You do not own this VPS.'))
        return
    component = (component or 'all').lower().strip()
    if component not in {'all','ssh','cloudflare','sshx','docker'}:
        await ctx.send(embed=create_error_embed('Invalid Component', 'Use `all`, `ssh`, `cloudflare`, `sshx`, or `docker`.'))
        return
    if str(vps.get('backend','lxc')).lower() == 'kvm':
        try:
            doctor = await kvm_guest_network_doctor(vps['container_name'], repair=True)
            nets = await wait_for_kvm_network(vps['container_name'], timeout=20)
            vps['networks'] = nets
            vps['ipv4'] = next(iter(nets.values()), None)
            save_vps_data_immediate()
            await ctx.send(embed=create_success_embed('🛠️ KVM Repair Complete', f"**VPS:** `{vps['container_name']}`\n**IPv4:** `{vps.get('ipv4') or 'NOT DETECTED'}`\n**DNS:** `{doctor.get('dns','UNKNOWN')}`\n**HTTPS:** `{doctor.get('https','UNKNOWN')}`\n\nUse `{PREFIX}kvm-network-repair {vps.get('id')}` for the detailed doctor."))
        except Exception as exc:
            await ctx.send(embed=create_error_embed('KVM Repair Failed', str(exc)[:1800]))
        return
    name=vps['container_name']; node_id=int(vps.get('node_id',1))
    await ctx.send(embed=create_info_embed('🛠️ VPS Repair', f'Repairing `{name}` component `{component}`…'))
    results=[]
    try:
        if component in ('all','ssh'):
            password=vps.get('root_password') or generate_strong_password(20)
            ok, detail=await configure_ssh(name,node_id,password)
            results.append(('SSH', ok, 'SSH configuration validated and restarted.' if ok else str(detail)[:700]))
        if component in ('all','docker'):
            try:
                await apply_lxc_config(name,node_id)
                results.append(('Docker/Nesting', True, 'LXC nesting, syscall interception and configured kernel modules applied.'))
            except Exception as exc:
                results.append(('Docker/Nesting', False, str(exc)[:700]))
        if component in ('all','sshx'):
            try:
                await _guest_exec_lxc(name,node_id,"set -e; if command -v apt-get >/dev/null 2>&1; then apt-get update -y >/dev/null 2>&1; apt-get install -y curl ca-certificates util-linux bash >/dev/null 2>&1; elif command -v apk >/dev/null 2>&1; then apk add --no-cache curl ca-certificates util-linux bash >/dev/null 2>&1; elif command -v dnf >/dev/null 2>&1; then dnf install -y curl ca-certificates util-linux bash >/dev/null 2>&1; elif command -v yum >/dev/null 2>&1; then yum install -y curl ca-certificates util-linux bash >/dev/null 2>&1; fi; command -v sshx >/dev/null 2>&1 || curl -sSf https://sshx.io/get | sh; command -v script >/dev/null 2>&1; command -v setsid >/dev/null 2>&1",timeout=120)
                results.append(('SSHX', True, 'SSHX and PTY dependencies are ready. Use Manage → SSHX to generate a fresh link.'))
            except Exception as exc:
                results.append(('SSHX', False, str(exc)[:700]))
        if component in ('all','cloudflare') and CLOUDFLARE_INSTALL_ENABLED:
            try:
                out=await asyncio.wait_for(_safe_cloudflare_install(name,node_id),timeout=300)
                results.append(('Cloudflare', 'CLOUDFLARED_SERVICE=ACTIVE' in (out or '') or 'CLOUDFLARED_INSTALLED=YES' in (out or ''), (out or '')[-700:]))
            except Exception as exc:
                results.append(('Cloudflare', False, str(exc)[:700]))
        report=await guest_health_report(vps)
        lines=[]
        for label,ok,detail in results:
            lines.append(f"{'✅' if ok else '⚠️'} **{label}:** {detail}")
        lines.append('')
        lines.append('**Post-repair health:**')
        for label,ok,detail in report.get('checks',[]):
            lines.append(f"{'✅' if ok else '⚠️'} {label}: {detail}")
        await ctx.send(embed=create_success_embed('🛠️ VPS Repair Complete', '\n'.join(lines)[:4000]))
    except Exception as e:
        await ctx.send(embed=create_error_embed('VPS Repair Failed', str(e)[:1800]))

@bot.command(name='cloudflare-fix')
@is_admin()
async def cloudflare_fix(ctx, vps_ref: str = None):
    """Install/repair cloudflared using either numeric VPS ID or container name."""
    if not vps_ref:
        await ctx.send(embed=create_error_embed('Missing VPS', f'Usage: `{PREFIX}cloudflare-fix <VPS ID or container-name>`\nExample: `{PREFIX}cloudflare-fix wbkajsydv-vps-1`'))
        return
    vps=resolve_vps_reference(vps_ref)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'No VPS matches `{vps_ref}`. Use `{PREFIX}myvps` to see the exact VPS/container name.'))
        return
    if vps.get('backend','lxc') != 'lxc':
        await ctx.send(embed=create_info_embed('☁️ Cloudflare + KVM', 'This repair path is for LXC. For KVM, use the guest SSH/cloud-init path.'))
        return
    try:
        node_id=int(vps.get('node_id',1)); name=vps['container_name']
        await ctx.send(embed=create_info_embed('☁️ Cloudflare Doctor', f'Checking `{name}` network and cloudflared state…'), ephemeral=False)
        diag=await cloudflare_guest_status(name,node_id)
        if 'INTERNET_OK' not in diag:
            await ctx.send(embed=create_error_embed('Cloudflare Network Check Failed', f'VPS `{name}` cannot reach Cloudflare yet. Fix guest DNS/internet first.\n```{diag[:1800]}```'))
            return
        out=await _safe_cloudflare_install(name,node_id)
        status=await cloudflare_guest_status(name,node_id)
        embed=create_success_embed('☁️ Cloudflare Repair Complete', f'Cloudflared was installed/repaired for `{name}`.\n\n```{out[-1400:]}```')
        add_field(embed, 'Health Check', f'```{status[:1800]}```', False)
        add_field(embed, 'Next Step', f'Use `{PREFIX}cloudflare-status {name}` to re-check later. A tunnel token/route is still required to publish a hostname.', False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed('Cloudflare Fix Failed',str(e)[:1800]))

@bot.command(name='cloudflare-status')
async def cloudflare_status(ctx, vps_ref: str = None):
    if not vps_ref:
        await ctx.send(embed=create_error_embed('Missing VPS', f'Usage: `{PREFIX}cloudflare-status <VPS ID or container-name>`'))
        return
    vps=resolve_vps_reference(vps_ref)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found',f'No VPS matches `{vps_ref}`.'))
        return
    owner_id=str(vps.get('user_id'))
    if str(ctx.author.id)!=owner_id and not is_admin_user_id(str(ctx.author.id)):
        await ctx.send(embed=create_error_embed('Access Denied','You do not own this VPS.')); return
    if vps.get('backend','lxc')!='lxc':
        await ctx.send(embed=create_info_embed('Cloudflare Status','Use the KVM guest SSH path to check cloudflared.')); return
    try:
        out=await cloudflare_guest_status(vps['container_name'],int(vps.get('node_id',1)))
        await ctx.send(embed=create_info_embed('☁️ Cloudflare Status',f'```{out[:2500]}```'))
    except Exception as e:
        await ctx.send(embed=create_error_embed('Cloudflare Status Failed',str(e)))

@bot.command(name='ptero-status')
@is_admin()
async def ptero_status(ctx):
    try:
        data=await ptero_request('GET','/api/application/nodes?per_page=1')
        await ctx.send(embed=create_success_embed('🦖 Pterodactyl Connected',f'Panel: `{PTERO_PANEL_URL}`\nNodes endpoint: **OK**\nNode records returned: `{len(data.get("data",[]))}`'))
    except Exception as e:
        await ctx.send(embed=create_error_embed('Pterodactyl Connection Failed',str(e)[:1800]))

@bot.command(name='ptero-nodes')
@is_admin()
async def ptero_nodes(ctx):
    try:
        data=await ptero_request('GET','/api/application/nodes?per_page=100')
        rows=[]
        for item in data.get('data',[]):
            a=item.get('attributes',{})
            rows.append(f"`{a.get('id')}` • **{a.get('name','?')}** • `{a.get('fqdn','?')}` • {'public' if a.get('public') else 'private'}")
        await ctx.send(embed=create_info_embed('🦖 Pterodactyl Nodes','\n'.join(rows)[:3800] or 'No nodes found.'))
    except Exception as e:
        await ctx.send(embed=create_error_embed('Pterodactyl Nodes Failed',str(e)[:1800]))

@bot.command(name='ptero-servers')
@is_admin()
async def ptero_servers(ctx):
    try:
        data=await ptero_request('GET','/api/application/servers?per_page=100')
        rows=[]
        for item in data.get('data',[]):
            a=item.get('attributes',{})
            rows.append(f"`{a.get('id')}` • **{a.get('name','?')}** • `{a.get('identifier','?')}` • node `{a.get('node','?')}`")
        await ctx.send(embed=create_info_embed('🦖 Pterodactyl Servers','\n'.join(rows)[:3800] or 'No servers found.'))
    except Exception as e:
        await ctx.send(embed=create_error_embed('Pterodactyl Servers Failed',str(e)[:1800]))

@bot.command(name='ptero-create')
@is_admin()
async def ptero_create(ctx, name: str, user_id: int, egg_id: int, allocation_id: int, ram_mb: int = 2048, disk_mb: int = 10240, cpu: int = 100):
    """Create a Pterodactyl server through the Application API."""
    if not 128 <= ram_mb <= 1048576 or not 512 <= disk_mb <= 4194304 or not 1 <= cpu <= 6400:
        await ctx.send(embed=create_error_embed('Invalid Resources','RAM/disk/CPU values are outside safe API limits.')); return
    payload={
      'name':name,'user':user_id,'nest':PTERO_DEFAULT_NEST_ID,'egg':egg_id,
      'docker_image':'ghcr.io/pterodactyl/yolks:debian','startup':'bash',
      'environment':{},'limits':{'memory':ram_mb,'swap':0,'disk':disk_mb,'io':500,'cpu':cpu},
      'feature_limits':{'databases':0,'allocations':1,'backups':0},
      'allocation':{'default':allocation_id}
    }
    try:
        data=await ptero_request('POST','/api/application/servers',payload)
        a=data.get('attributes',{})
        await ctx.send(embed=create_success_embed('🦖 Pterodactyl Server Created',f"Name: **{a.get('name',name)}**\nID: `{a.get('id','?')}`\nIdentifier: `{a.get('identifier','?')}`"))
    except Exception as e:
        await ctx.send(embed=create_error_embed('Pterodactyl Create Failed',str(e)[:2000]))

@bot.command(name='resource-check')
@is_admin()
async def resource_check(ctx):
    suspended_count = 0
    embed = create_info_embed("Resource Check", "Checking all running VPS for high resource usage...")
    msg = await ctx.send(embed=embed)
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps.get('status') == 'running' and not vps.get('suspended', False) and not vps.get('whitelisted', False):
                container = vps['container_name']
                node_id = vps['node_id']
                stats = await get_container_stats(container, node_id)
                cpu = stats['cpu']
                ram = stats['ram']['pct']
                if cpu > CPU_THRESHOLD or ram > RAM_THRESHOLD:
                    reason = f"High resource usage: CPU {cpu:.1f}%, RAM {ram:.1f}% (threshold: {CPU_THRESHOLD}% CPU / {RAM_THRESHOLD}% RAM)"
                    logger.warning(f"Suspending {container}: {reason}")
                    try:
                        await execute_lxc(container, f"stop {container}", node_id=node_id)
                        vps['status'] = 'stopped'
                        vps['suspended'] = True
                        if 'suspension_history' not in vps:
                            vps['suspension_history'] = []
                        vps['suspension_history'].append({
                            'time': datetime.now().isoformat(),
                            'reason': reason,
                            'by': 'Manual Resource Check'
                        })
                        save_vps_data()
                        try:
                            owner = await bot.fetch_user(int(user_id))
                            warn_embed = create_warning_embed("🚨 VPS Auto-Suspended", f"Your VPS `{container}` has been suspended due to high resource usage.\n\n**Reason:** {reason}\n\nContact admin to unsuspend and address the issue.")
                            await owner.send(embed=warn_embed)
                        except Exception as dm_e:
                            logger.error(f"Failed to DM owner {user_id}: {dm_e}")
                        suspended_count += 1
                    except Exception as e:
                        logger.error(f"Failed to suspend {container}: {e}")
    final_embed = create_info_embed("Resource Check Complete", f"Checked all VPS. Suspended {suspended_count} high-usage VPS.")
    await msg.edit(embed=final_embed)

@bot.command(name='whitelist-vps')
@is_admin()
async def whitelist_vps(ctx, container_name: str, action: str):
    if action.lower() not in ['add', 'remove']:
        await ctx.send(embed=create_error_embed("Invalid Action", f"Use: `{PREFIX}whitelist-vps <container> <add|remove>`"))
        return
    found = False
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps['container_name'] == container_name:
                if action.lower() == 'add':
                    vps['whitelisted'] = True
                    msg = "added to whitelist (exempt from auto-suspension)"
                else:
                    vps['whitelisted'] = False
                    msg = "removed from whitelist"
                save_vps_data()
                await ctx.send(embed=create_success_embed("Whitelist Updated", f"VPS `{container_name}` {msg}."))
                found = True
                break
        if found:
            break
    if not found:
        await ctx.send(embed=create_error_embed("Not Found", f"VPS `{container_name}` not found."))

@bot.command(name='repair-ports')
@is_admin()
async def repair_ports(ctx, container_name: str):
    await ctx.send(embed=create_info_embed("Repairing Ports", f"Re-adding port forward devices for `{container_name}`..."))
    try:
        readded = await recreate_port_forwards(container_name)
        await ctx.send(embed=create_success_embed("Ports Repaired", f"Re-added {readded} port forwards for `{container_name}`."))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Repair Failed", f"Error: {str(e)}"))

@bot.command(name='set-expiration')
@is_admin()
async def set_expiration(ctx, container_name: str, days: int):
    """Set VPS expiration date (admin only)"""
    if days <= 0:
        await ctx.send(embed=create_error_embed("Invalid Days", "Days must be a positive number."))
        return
    
    found_vps = None
    user_id = None
    vps_index = None
    
    for uid, vps_list in vps_data.items():
        for i, vps in enumerate(vps_list):
            if vps['container_name'] == container_name:
                found_vps = vps
                user_id = uid
                vps_index = i
                break
        if found_vps:
            break
    
    if not found_vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
        return
    
    # Calculate expiration date
    expiration_date = (datetime.now() + timedelta(days=days)).isoformat()
    found_vps['expiration_date'] = expiration_date
    vps_data[user_id][vps_index] = found_vps
    save_vps_data()
    
    # Get owner info
    try:
        owner = await bot.fetch_user(int(user_id))
        owner_mention = owner.mention
    except:
        owner_mention = f"User {user_id}"
    
    embed = create_success_embed("Expiration Date Set", 
        f"VPS `{container_name}` expiration date set for {days} days from now")
    add_field(embed, "Owner", owner_mention, True)
    add_field(embed, "Expires On", datetime.fromisoformat(expiration_date).strftime('%Y-%m-%d %H:%M:%S'), True)
    add_field(embed, "Days Remaining", str(days), True)
    
    await ctx.send(embed=embed)
    
    # Notify owner
    try:
        owner = await bot.fetch_user(int(user_id))
        dm_embed = create_info_embed("⏰ VPS Expiration Date Set",
            f"Your VPS `{container_name}` will expire in {days} days.\n\n"
            f"**Expires:** {datetime.fromisoformat(expiration_date).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Contact admin to renew your VPS before it expires.")
        await owner.send(embed=dm_embed)
    except:
        pass

@bot.command(name='renew-vps')
@is_admin()
async def renew_vps(ctx, container_name: str, additional_days: int = None):
    """Renew VPS expiration date (admin only)"""
    if additional_days is None:
        additional_days = DEFAULT_VPS_EXPIRATION_DAYS
    
    if additional_days <= 0:
        await ctx.send(embed=create_error_embed("Invalid Days", "Days must be a positive number."))
        return
    
    found_vps = None
    user_id = None
    vps_index = None
    
    for uid, vps_list in vps_data.items():
        for i, vps in enumerate(vps_list):
            if vps['container_name'] == container_name:
                found_vps = vps
                user_id = uid
                vps_index = i
                break
        if found_vps:
            break
    
    if not found_vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
        return
    
    # Get current expiration or use today
    if found_vps.get('expiration_date'):
        current_expiration = datetime.fromisoformat(found_vps['expiration_date'])
    else:
        current_expiration = datetime.now()
    
    # Calculate new expiration date
    new_expiration_date = (current_expiration + timedelta(days=additional_days)).isoformat()
    found_vps['expiration_date'] = new_expiration_date
    
    # Unsuspend if it was suspended due to expiration
    if found_vps.get('suspended', False):
        found_vps['suspended'] = False
    
    vps_data[user_id][vps_index] = found_vps
    save_vps_data()
    
    # Get owner info
    try:
        owner = await bot.fetch_user(int(user_id))
        owner_mention = owner.mention
    except:
        owner_mention = f"User {user_id}"
    
    embed = create_success_embed("VPS Renewed", 
        f"VPS `{container_name}` has been renewed")
    add_field(embed, "Owner", owner_mention, True)
    add_field(embed, "Added Days", str(additional_days), True)
    add_field(embed, "Previous Expiration", current_expiration.strftime('%Y-%m-%d %H:%M:%S'), True)
    add_field(embed, "New Expiration", datetime.fromisoformat(new_expiration_date).strftime('%Y-%m-%d %H:%M:%S'), True)
    
    await ctx.send(embed=embed)
    
    # Notify owner
    try:
        owner = await bot.fetch_user(int(user_id))
        dm_embed = create_success_embed("✅ VPS Renewed",
            f"Your VPS `{container_name}` has been renewed!\n\n"
            f"**New Expiration:** {datetime.fromisoformat(new_expiration_date).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Thank you for using {BOT_NAME}!")
        await owner.send(embed=dm_embed)
    except:
        pass

@bot.command(name='vps-expiration')
@is_admin()
async def check_expiration(ctx, container_name: str = None):
    """Check VPS expiration status (admin only)"""
    if container_name:
        # Check specific VPS
        found_vps = None
        user_id = None
        
        for uid, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    found_vps = vps
                    user_id = uid
                    break
            if found_vps:
                break
        
        if not found_vps:
            await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
            return
        
        # Get owner info
        try:
            owner = await bot.fetch_user(int(user_id))
            owner_mention = owner.mention
        except:
            owner_mention = f"User {user_id}"
        
        embed = create_info_embed("VPS Expiration Status", f"Details for `{container_name}`")
        add_field(embed, "Owner", owner_mention, True)
        add_field(embed, "Container", f"`{container_name}`", True)
        
        if found_vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(found_vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            
            if days_remaining < 0:
                status = "🔴 EXPIRED"
                color = 0xff3366
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                status = "🟡 EXPIRING SOON"
                color = 0xffaa00
            else:
                status = "🟢 ACTIVE"
                color = 0x00ff88
            
            embed.color = color
            add_field(embed, "Status", status, True)
            add_field(embed, "Expiration Date", expiration_dt.strftime('%Y-%m-%d %H:%M:%S'), True)
            add_field(embed, "Days Remaining", str(max(0, days_remaining)), True)
        else:
            add_field(embed, "Status", "🔵 NO EXPIRATION SET", False)
        
        await ctx.send(embed=embed)
    else:
        # List all VPS with expiration status
        embed = create_info_embed("📋 All VPS Expiration Status", "Global expiration overview")
        
        expiring_soon = []
        expired = []
        active = []
        no_expiration = []
        
        for user_id, vps_list in vps_data.items():
            try:
                owner = await bot.fetch_user(int(user_id))
                owner_name = owner.name
            except:
                owner_name = f"Unknown ({user_id})"
            
            for vps in vps_list:
                if vps.get('expiration_date'):
                    expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                    days_remaining = (expiration_dt - datetime.now()).days
                    
                    status_line = f"**{owner_name}** - `{vps['container_name']}`\n" \
                                 f"Expires: {expiration_dt.strftime('%Y-%m-%d')} ({days_remaining} days)"
                    
                    if days_remaining < 0:
                        expired.append(status_line)
                    elif days_remaining <= EXPIRATION_WARNING_DAYS:
                        expiring_soon.append(status_line)
                    else:
                        active.append(status_line)
                else:
                    no_expiration.append(f"**{owner_name}** - `{vps['container_name']}`")
        
        if expiring_soon:
            add_field(embed, "🟡 Expiring Soon", "\n\n".join(expiring_soon), False)
        if expired:
            add_field(embed, "🔴 Expired", "\n\n".join(expired), False)
        if active:
            add_field(embed, "🟢 Active", "\n\n".join(active[:10]), False)
            if len(active) > 10:
                add_field(embed, "Note", f"Showing 10 of {len(active)} active VPS", False)
        if no_expiration:
            add_field(embed, "🔵 No Expiration Set", "\n".join(no_expiration[:5]), False)
            if len(no_expiration) > 5:
                add_field(embed, "Note", f"Total {len(no_expiration)} VPS without expiration date", False)
        
        await ctx.send(embed=embed)

@bot.command(name='about')
async def about(ctx):
    total_users = len(vps_data)
    total_vps = sum(len(vps_list) for vps_list in vps_data.values())
    latency = round(bot.latency * 1000)
    main_admin = await bot.fetch_user(MAIN_ADMIN_ID)
    embed = create_info_embed(f"About {BOT_NAME}", f"Bot information and statistics")
    if BOT_BANNER_URL:
        embed.set_image(url=BOT_BANNER_URL)
    add_field(embed, "Bot Name", BOT_NAME, True)
    add_field(embed, "Main Owner", main_admin.mention, True)
    add_field(embed, "Developer", BOT_DEVELOPER, True)
    add_field(embed, "Ping", f"{latency}ms", True)
    add_field(embed, "Version", BOT_VERSION, True)
    add_field(embed, "Total VPS", str(total_vps), True)
    add_field(embed, "Total Users", str(total_users), True)
    await ctx.send(embed=embed)


@bot.command(name='quickhelp')
async def quick_help(ctx):
    """Show quick reference for common tasks"""
    user_id = str(ctx.author.id)
    is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
    
    embed = create_info_embed("🚀 Quick Help Reference", 
        f"Quick reference for common tasks. Use `{PREFIX}help` for complete command list.")
    
    # Common user tasks
    add_field(embed, "👤 For Users", 
        f"• `{PREFIX}myvps` - List your VPS\n"
        f"• `{PREFIX}manage` - Start/stop/manage VPS\n"
        f"• `{PREFIX}ports` - Manage port forwarding\n"
        f"• `{PREFIX}share-user @user 1` - Share VPS #1\n"
        f"• `{PREFIX}about` - Bot information", False)
    
    # VPS management
    add_field(embed, "🖥️ VPS Control", 
        f"• In `{PREFIX}manage`: Click ▶ to start VPS\n"
        f"• In `{PREFIX}manage`: Click ⏸ to stop VPS\n"
        f"• In `{PREFIX}manage`: Click 🔑 for SSH access\n"
        f"• In `{PREFIX}manage`: Click 📊 for live stats\n"
        f"• In `{PREFIX}manage`: Click 🔄 to reinstall OS", False)
    
    # Troubleshooting
    add_field(embed, "🔧 Common Issues", 
        f"• Ports not working? Use `{PREFIX}repair-ports <container>` (admin)\n"
        "• VPS suspended? Contact admin to unsuspend\n"
        "• Need more resources? Contact admin for upgrade\n"
        "• SSH not working? Try reinstall with different OS", False)
    
    if is_admin_user:
        add_field(embed, "🛡️ Admin Quick Actions", 
            f"• `{PREFIX}create 2 2 20 @user` - Create 2GB/2CPU/20GB VPS\n"
            f"• `{PREFIX}userinfo @user` - Check user details\n"
            f"• `{PREFIX}node list` - List all nodes\n"
            f"• `{PREFIX}serverstats` - System overview\n"
            f"• `{PREFIX}suspend-vps <container> <reason>` - Suspend VPS\n"
            f"• `{PREFIX}vps-audit` - Audit DB vs LXC\n"
            f"• `{PREFIX}vps-sync` - Sync VPS status\n"
            f"• `{PREFIX}os-list` - View supported OS images", False)
    
    embed.set_footer(text=f"AxionHost • Use {PREFIX}help for complete command list")
    await ctx.send(embed=embed)

@bot.command(name='help-search')
async def help_search(ctx, *, search_term: str = None):
    """Search for commands"""
    if not search_term:
        await show_help(ctx)
        return
    
    search_term = search_term.lower()
    user_id = str(ctx.author.id)
    is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
    is_main_admin_user = user_id == str(MAIN_ADMIN_ID)
    
    # Build complete command list based on permissions
    all_commands = []
    
    # User commands (always available)
    user_categories = ["user", "vps", "ports", "system", "bot"]
    for cat in user_categories:
        all_commands.extend(HelpView(ctx).command_categories[cat]["commands"])
    
    # Admin commands
    if is_admin_user:
        all_commands.extend(HelpView(ctx).command_categories["admin"]["commands"])
        all_commands.extend(HelpView(ctx).command_categories["nodes"]["commands"])
    
    # Main admin commands
    if is_main_admin_user:
        all_commands.extend(HelpView(ctx).command_categories["main_admin"]["commands"])
    
    # Search through commands
    matches = []
    for cmd, desc in all_commands:
        if (search_term in cmd.lower() or search_term in desc.lower()):
            matches.append((cmd, desc))
    
    if not matches:
        embed = create_info_embed("🔍 No Results Found",
            f"No commands found matching '{search_term}'. Try a different search term.")
        await ctx.send(embed=embed)
        return
    
    # Show results
    embed = create_info_embed(f"🔍 Search Results for '{search_term}'",
        f"Found {len(matches)} command(s) matching your search.")
    
    # Group matches by category
    results_text = "\n".join([f"**{cmd}** - {desc}" for cmd, desc in matches[:15]])
    add_field(embed, "Matching Commands", results_text, False)
    
    if len(matches) > 15:
        add_field(embed, "Note", f"Showing 15 of {len(matches)} matches. Try a more specific search.", False)
    
    embed.set_footer(text=f"AxionHost • Use {PREFIX}help for complete list")
    await ctx.send(embed=embed)    

@bot.command(name='node')
@is_admin()
async def node_cmd(ctx, sub: str, *args):
    if sub == 'create':
        await ctx.send("Enter node name:")
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        name = (await bot.wait_for('message', check=check)).content.strip()
        await ctx.send("Enter location:")
        location = (await bot.wait_for('message', check=check)).content.strip()
        await ctx.send("Enter total VPS capacity:")
        total_vps_str = (await bot.wait_for('message', check=check)).content.strip()
        try:
            total_vps = int(total_vps_str)
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid Input", "Total VPS must be an integer."))
            return
        await ctx.send("Enter tags (comma separated):")
        tags_str = (await bot.wait_for('message', check=check)).content.strip()
        tags = [t.strip() for t in tags_str.split(',') if t.strip()]
        tags_json = json.dumps(tags)
        await ctx.send("Enter node URL (e.g., http://ip:port or https://ip:port) or leave blank for local:")
        url_str = (await bot.wait_for('message', check=check)).content.strip()
        
        # Normalize URL if provided
        if url_str:
            if not url_str.startswith('http://') and not url_str.startswith('https://'):
                url_str = f'http://{url_str}'
            url = url_str
        else:
            url = None
        
        is_local = 1 if not url else 0
        api_key = None if is_local else ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute('INSERT INTO nodes (name, location, total_vps, tags, api_key, url, is_local) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (name, location, total_vps, tags_json, api_key, url, is_local))
            conn.commit()
            node_id = cur.lastrowid
            # The first created remote node becomes the persisted deployment default
            # when no default has been configured yet. This prevents node 1/local/US
            # from being selected merely because it has the lowest database ID.
            try:
                current_default = int(str(get_setting('default_node_id', '0') or '0'))
            except (TypeError, ValueError):
                current_default = 0
            normalized_node_name = str(name or '').strip().lower()
            wants_default = normalized_node_name in {'default', 'default node', 'primary', 'primary node'} or 'default node' in normalized_node_name
            if not is_local and (current_default <= 0 or wants_default):
                set_setting('default_node_id', str(node_id))
                default_note = '\n⭐ **Default deployment node:** Yes'
            else:
                default_note = ''
            embed = create_success_embed("Node Created", f"ID: {node_id}\nName: {name}\nLocation: {location}\nCapacity: {total_vps}\nTags: {', '.join(tags)}{default_note}")
            if not is_local:
                add_field(embed, "API Key", api_key, False)
                add_field(embed, "URL", url, False)
                add_field(embed, "Setup", f"Run `python node-agent.py --api_key={api_key} --port=PORT` on the node server.")
            await ctx.send(embed=embed)
        except sqlite3.IntegrityError:
            await ctx.send(embed=create_error_embed("Error", "Node name already exists."))
        conn.close()
    elif sub == 'list':
        nodes = get_nodes()
        embed = create_info_embed("Nodes List", "")
        for n in nodes:
            status = "Local" if n['is_local'] else "Down"
            if not n['is_local']:
                try:
                    response = await http_request('GET', f"{n['url']}/api/ping", params={'api_key': n['api_key']}, timeout=5)
                    status = "Up" if response.status_code == 200 else "Down"
                except:
                    pass
            field = f"ID: {n['id']}\nName: {n['name']}\nLocation: {n['location']}\nCapacity: {n['total_vps']}\nTags: {', '.join(n['tags'])}\nStatus: {status}"
            if not n['is_local']:
                field += f"\nURL: {n['url']}"
            add_field(embed, f"Node {n['id']}", field, False)
        await ctx.send(embed=embed)
    elif sub == 'edit':
        if not args:
            await ctx.send(embed=create_error_embed("Usage", f"{PREFIX}node edit <id>"))
            return
        try:
            node_id = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid ID", "Node ID must be an integer."))
            return
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed("Not Found", "Node not found."))
            return
        await ctx.send(f"Editing node {node['name']}. Enter new name ( . to skip):")
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        new_name = (await bot.wait_for('message', check=check)).content.strip()
        if new_name != '.':
            node['name'] = new_name
        await ctx.send("New location ( . to skip):")
        new_loc = (await bot.wait_for('message', check=check)).content.strip()
        if new_loc != '.':
            node['location'] = new_loc
        await ctx.send("New total VPS capacity ( . to skip):")
        new_total = (await bot.wait_for('message', check=check)).content.strip()
        if new_total != '.':
            node['total_vps'] = int(new_total)
        await ctx.send("New tags (comma separated, . to skip):")
        new_tags = (await bot.wait_for('message', check=check)).content.strip()
        if new_tags != '.':
            node['tags'] = json.dumps([t.strip() for t in new_tags.split(',') if t.strip()])
        
        # NEW: Add conversion option between Local and Dynamic
        if node['is_local']:
            await ctx.send("Convert Local Node to Dynamic URL-based Node? (y/n):")
            convert = (await bot.wait_for('message', check=check)).content.strip().lower()
            if convert == 'y':
                await ctx.send("Enter node URL (e.g., http://ip:port or https://ip:port):")
                url_str = (await bot.wait_for('message', check=check)).content.strip()
                if not url_str:
                    await ctx.send(embed=create_error_embed("Error", "URL cannot be empty for dynamic node."))
                    return
                
                # Normalize URL - add http:// if not present
                if not url_str.startswith('http://') and not url_str.startswith('https://'):
                    url_str = f'http://{url_str}'
                
                node['url'] = url_str
                node['is_local'] = 0
                node['api_key'] = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))
                await ctx.send(f"✅ Node converted to Dynamic!\n\n**URL:** `{url_str}`\n**Generated API Key:** `{node['api_key']}`\n\n**Setup Command:**\n```\npython node-agent.py --api_key={node['api_key']} --port=PORT\n```")
        else:
            await ctx.send("Convert Dynamic Node to Local? (y/n):")
            convert = (await bot.wait_for('message', check=check)).content.strip().lower()
            if convert == 'y':
                node['url'] = None
                node['api_key'] = None
                node['is_local'] = 1
                await ctx.send("✅ Node converted to Local!")
            else:
                await ctx.send("New URL ( . to skip):")
                new_url = (await bot.wait_for('message', check=check)).content.strip()
                if new_url != '.':
                    # Normalize URL - add http:// if not present
                    if not new_url.startswith('http://') and not new_url.startswith('https://'):
                        new_url = f'http://{new_url}'
                    node['url'] = new_url
                await ctx.send("Regenerate API key? (y/n):")
                regen = (await bot.wait_for('message', check=check)).content.strip().lower()
                if regen == 'y':
                    node['api_key'] = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute('UPDATE nodes SET name=?, location=?, total_vps=?, tags=?, api_key=?, url=?, is_local=? WHERE id=?',
                    (node['name'], node['location'], node['total_vps'], json.dumps(node['tags']), node.get('api_key'), node.get('url'), node['is_local'], node_id))
        conn.commit()
        conn.close()
        # If an edited default node was converted to local, repair the default
        # immediately so future deployments never drift back to node 1.
        if _configured_default_node_id() == int(node_id) and REMOTE_NODE_ONLY and bool(node.get('is_local')):
            remote_nodes = [n for n in get_nodes() if not bool(n.get('is_local'))]
            remote_nodes.sort(key=lambda n: int(n.get('id') or 0))
            set_setting('default_node_id', str(remote_nodes[0]['id']) if remote_nodes else '0')
        embed = create_success_embed("Node Updated", f"ID: {node_id}\nName: {node['name']}\nLocation: {node['location']}\nCapacity: {node['total_vps']}\nTags: {', '.join(node['tags'])}\nType: {'Local' if node['is_local'] else 'Dynamic'}")
        if not node['is_local']:
            add_field(embed, "API Key", node['api_key'], False)
            add_field(embed, "URL", node['url'], False)
        await ctx.send(embed=embed)
    
    # NEW: Add delete subcommand
    elif sub == 'delete':
        if not args:
            await ctx.send(embed=create_error_embed("Usage", f"{PREFIX}node delete <id> [force]"))
            return
        
        try:
            node_id = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid ID", "Node ID must be an integer."))
            return
        
        force = False
        if len(args) > 1 and args[1].lower() == 'force':
            force = True
        elif len(args) > 1:
            await ctx.send(embed=create_error_embed("Invalid Argument", "Optional argument must be 'force'."))
            return
        
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed("Not Found", "Node not found."))
            return
        
        # Check if this is the local node
        if node['is_local']:
            await ctx.send(embed=create_error_embed("Cannot Delete", "Cannot delete the local node."))
            return
        
        # Check if node has any VPS assigned
        vps_count = get_current_vps_count(node_id)
        if not force and vps_count > 0:
            await ctx.send(embed=create_error_embed("Cannot Delete", 
                f"Node has {vps_count} VPS assigned. Migrate or delete them first, or use 'force' to delete all VPS and the node."))
            return
        
        # Prepare warning message
        warning_msg = f"Are you sure you want to delete node **{node['name']}** (ID: {node_id})?\n\n"
        warning_msg += f"**Location:** {node['location']}\n"
        warning_msg += f"**Tags:** {', '.join(node['tags'])}\n\n"
        if force and vps_count > 0:
            warning_msg += f"**WARNING: Force mode will delete all {vps_count} VPS on this node first!**\n\n"
        warning_msg += "This action cannot be undone!"
        
        embed = create_warning_embed("⚠️ Delete Node", warning_msg)
        
        class ConfirmDelete(discord.ui.View):
            def __init__(self, node_id, node_name, force, vps_count):
                super().__init__(timeout=60)
                self.node_id = node_id
                self.node_name = node_name
                self.force = force
                self.vps_count = vps_count
            
            @discord.ui.button(label="Delete Node", style=discord.ButtonStyle.danger)
            async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
                if str(inter.user.id) != str(ctx.author.id):
                    await inter.response.send_message(
                        embed=create_error_embed("Access Denied", "Only the command author can confirm."),
                        ephemeral=True
                    )
                    return
                
                await inter.response.defer()
                
                conn = get_db()
                cur = conn.cursor()
                
                if self.force and self.vps_count > 0:
                    # Force delete all VPS on this node
                    cur.execute('DELETE FROM vps WHERE node_id = ?', (self.node_id,))
                
                # Delete the node from database
                cur.execute('DELETE FROM nodes WHERE id = ?', (self.node_id,))
                
                conn.commit()
                conn.close()

                # If the deleted node was the deployment default, choose the next
                # configured remote node. Never silently restore node 1/local.
                try:
                    if _configured_default_node_id() == int(self.node_id):
                        remote_nodes = [n for n in get_nodes() if not bool(n.get('is_local'))] if REMOTE_NODE_ONLY else get_nodes()
                        remote_nodes.sort(key=lambda n: int(n.get('id') or 0))
                        set_setting('default_node_id', str(remote_nodes[0]['id']) if remote_nodes else '0')
                except Exception as exc:
                    logger.warning('Could not repair persisted default node after deletion: %s', type(exc).__name__)
                
                msg = f"Node **{self.node_name}** (ID: {self.node_id}) has been deleted."
                if self.force and self.vps_count > 0:
                    msg += f" All {self.vps_count} VPS on the node were also deleted."
                
                success_embed = create_success_embed("Node Deleted", msg)
                await inter.followup.send(embed=success_embed)
                self.stop()
            
            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
                if str(inter.user.id) != str(ctx.author.id):
                    await inter.response.send_message(
                        embed=create_error_embed("Access Denied", "Only the command author can cancel."),
                        ephemeral=True
                    )
                    return
                
                await inter.response.edit_message(
                    embed=create_info_embed("Deletion Cancelled", "Node deletion was cancelled."),
                    view=None
                )
                self.stop()
        
        await ctx.send(embed=embed, view=ConfirmDelete(node_id, node['name'], force, vps_count))
    
    elif sub in ('default', 'set-default', 'primary'):
        if not args:
            current = _configured_default_node_id()
            node = get_node(current) if current > 0 else None
            if node:
                await ctx.send(embed=create_info_embed('⭐ Default Node', f"Current default: **{node['name']}** (ID `{current}`)\nLocation: `{node.get('location') or 'Unknown'}`"))
            else:
                await ctx.send(embed=create_info_embed('⭐ Default Node', 'No deployment default is configured.'))
            return
        try:
            node_id = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed('Invalid ID', 'Node ID must be an integer.'))
            return
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed('Not Found', f'Node `{node_id}` is not configured.'))
            return
        if REMOTE_NODE_ONLY and bool(node.get('is_local')):
            await ctx.send(embed=create_error_embed('Invalid Default', 'Remote-only mode is enabled. The default deployment node must be a remote node, not the local controller.'))
            return
        if REMOTE_NODE_ONLY:
            ok, reason, latency = await _probe_remote_node(node, attempts=3, timeout=4.0)
            if not ok:
                await ctx.send(embed=create_error_embed('Remote Node Unreachable', f"Node **{node['name']}** (ID `{node_id}`) cannot be reached.\n\nReason: `{reason}`\nURL: `{node.get('url') or 'missing'}`\n\nFix the remote agent/API URL and API key, then run `{PREFIX}node default {node_id}` again."))
                return
            status_note = f"\nLatency: `{latency:.0f} ms`"
        else:
            status_note = ''
        set_setting('default_node_id', str(node_id))
        await ctx.send(embed=create_success_embed('⭐ Default Node Updated', f"New default deployment node: **{node['name']}** (ID `{node_id}`)\nLocation: `{node.get('location') or 'Unknown'}`{status_note}\n\nNew VPS deployments will use this node by default."))

    elif sub in ('auto-default', 'repair-default'):
        candidates = _remote_candidates() if REMOTE_NODE_ONLY else sorted(get_nodes(), key=lambda n: int(n.get('id') or 0))
        if not candidates:
            await ctx.send(embed=create_error_embed('No Remote Nodes', 'Remote-only mode is enabled but no remote node is configured.'))
            return
        results = []
        healthy = []
        for candidate in candidates:
            if candidate.get('is_local'):
                continue
            ok, reason, latency = await _probe_remote_node(candidate, attempts=2, timeout=3.0)
            results.append(f"• `{candidate['id']}` {candidate['name']}: {'🟢' if ok else '🔴'} {reason}")
            if ok:
                healthy.append((latency, int(candidate['id']), candidate))
        if not healthy:
            await ctx.send(embed=create_error_embed('No Healthy Remote Node', 'No remote node passed the authenticated API health check.\n\n' + '\n'.join(results)[:3300]))
            return
        healthy.sort(key=lambda x: (x[0], x[1]))
        _, selected_id, selected = healthy[0]
        set_setting('default_node_id', str(selected_id))
        await ctx.send(embed=create_success_embed('⭐ Default Node Repaired', f"Selected **{selected['name']}** (ID `{selected_id}`) as the remote deployment default.\nLatency: `{healthy[0][0]:.0f} ms`\n\n" + '\n'.join(results)))

    elif sub == 'set-slots':
        if len(args) < 2:
            await ctx.send(embed=create_error_embed("Usage", f"{PREFIX}node set-slots <id> <slots>"))
            return
        try:
            node_id, slots = int(args[0]), int(args[1])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid Input", "Node ID and slots must be integers."))
            return
        if slots < 1:
            await ctx.send(embed=create_error_embed("Invalid Slots", "Slots must be at least 1."))
            return
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed("Not Found", "Node not found."))
            return
        current = get_current_vps_count(node_id)
        if slots < current:
            await ctx.send(embed=create_error_embed("Slots Too Low", f"Node currently has `{current}` VPS. Slots cannot be lower than current usage."))
            return
        conn = get_db()
        conn.execute('UPDATE nodes SET total_vps=? WHERE id=?', (slots, node_id))
        conn.commit(); conn.close()
        await ctx.send(embed=create_success_embed("Node Slots Updated", f"**Node:** `{node['name']}` (ID `{node_id}`)\n**Used:** `{current}`\n**Total slots:** `{slots}`\n**Available:** `{slots-current}`"))

    elif sub == 'status':
        # New: Check node status
        if not args:
            await ctx.send(embed=create_error_embed("Usage", f"{PREFIX}node status <id>"))
            return
        
        try:
            node_id = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid ID", "Node ID must be an integer."))
            return
        
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed("Not Found", "Node not found."))
            return
        
        embed = create_info_embed(f"Node Status - {node['name']}")
        
        if node['is_local']:
            status = "🟢 Local Node"
            cpu_usage = get_host_cpu_usage()
            ram_usage = get_host_ram_usage()
            add_field(embed, "Status", status, True)
            add_field(embed, "CPU Usage", f"{cpu_usage:.1f}%", True)
            add_field(embed, "RAM Usage", f"{ram_usage:.1f}%", True)
        else:
            try:
                response = await http_request('GET', f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
                if response.status_code == 200:
                    status = "🟢 Online"
                    try:
                        stats_response = await http_request('GET', f"{node['url']}/api/get_host_stats", 
                                                    params={'api_key': node['api_key']}, 
                                                    timeout=5)
                        if stats_response.status_code == 200:
                            stats = stats_response.json()
                            cpu_usage = stats.get('cpu', 0.0)
                            ram_usage = stats.get('ram', 0.0)
                            add_field(embed, "CPU Usage", f"{cpu_usage:.1f}%", True)
                            add_field(embed, "RAM Usage", f"{ram_usage:.1f}%", True)
                    except:
                        cpu_usage = "Unknown"
                        ram_usage = "Unknown"
                else:
                    status = "🔴 Offline"
            except:
                status = "🔴 Offline"
            
            add_field(embed, "Status", status, True)
        
        vps_count = get_current_vps_count(node_id)
        capacity = node['total_vps']
        usage_percentage = (vps_count / capacity * 100) if capacity > 0 else 0
        
        available_slots = max(0, int(capacity) - int(vps_count))
        add_field(embed, "VPS Slots", f"**Used:** `{vps_count}`\n**Total:** `{capacity}`\n**Available:** `{available_slots}`\n**Usage:** `{usage_percentage:.1f}%`", True)
        add_field(embed, "Location", node['location'], True)
        add_field(embed, "Tags", ", ".join(node['tags']), True)
        
        if not node['is_local']:
            add_field(embed, "URL", node['url'], False)
        
        await ctx.send(embed=embed)
    
    elif sub == 'regen-key':
        # NEW: Regenerate API key for dynamic node
        if not args:
            await ctx.send(embed=create_error_embed("Usage", f"{PREFIX}node regen-key <id>"))
            return
        
        try:
            node_id = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid ID", "Node ID must be an integer."))
            return
        
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed("Not Found", "Node not found."))
            return
        
        # Check if node is local
        if node['is_local']:
            await ctx.send(embed=create_error_embed("Error", "Cannot regenerate API key for Local nodes. Only Dynamic nodes have API keys."))
            return
        
        # Confirm regeneration
        warning_embed = create_warning_embed("⚠️ Regenerate API Key", 
            f"You are about to regenerate the API key for node **{node['name']}**.\n\n"
            f"**Current API Key:** `{node['api_key']}`\n\n"
            f"**This action will:**\n"
            f"• Generate a new 32-character API key\n"
            f"• Invalidate the old API key\n"
            f"• Require updating the remote node agent\n\n"
            f"Are you sure you want to continue?")
        
        class ConfirmRegenKey(discord.ui.View):
            def __init__(self, node_id, node):
                super().__init__(timeout=60)
                self.node_id = node_id
                self.node = node
            
            @discord.ui.button(label="Regenerate Key", style=discord.ButtonStyle.danger)
            async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
                if str(inter.user.id) != str(ctx.author.id):
                    await inter.response.send_message(
                        embed=create_error_embed("Access Denied", "Only the command author can confirm."),
                        ephemeral=True
                    )
                    return
                
                await inter.response.defer()
                
                # Generate new API key
                new_api_key = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))
                
                # Update database
                conn = get_db()
                cur = conn.cursor()
                cur.execute('UPDATE nodes SET api_key=? WHERE id=?', (new_api_key, self.node_id))
                conn.commit()
                conn.close()
                
                # Create success embed with new key
                success_embed = create_success_embed("✅ API Key Regenerated", 
                    f"Node **{self.node['name']}** (ID: {self.node_id})")
                
                add_field(success_embed, "Old API Key", f"`{self.node['api_key']}`", False)
                add_field(success_embed, "New API Key", f"`{new_api_key}`", False)
                add_field(success_embed, "Node URL", self.node['url'], True)
                
                setup_command = f"python node-agent.py --api_key={new_api_key} --port=PORT"
                add_field(success_embed, "Update Remote Agent", 
                    f"SSH to the remote server and restart with:\n```\n{setup_command}\n```", False)
                
                add_field(success_embed, "⚠️ Important", 
                    "The old API key is now invalid. Update your remote node agent immediately.", False)
                
                await inter.followup.send(embed=success_embed)
                self.stop()
            
            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
                if str(inter.user.id) != str(ctx.author.id):
                    await inter.response.send_message(
                        embed=create_error_embed("Access Denied", "Only the command author can cancel."),
                        ephemeral=True
                    )
                    return
                
                await inter.response.edit_message(
                    embed=create_info_embed("Cancelled", "API key regeneration was cancelled."),
                    view=None
                )
                self.stop()
        
        await ctx.send(embed=warning_embed, view=ConfirmRegenKey(node_id, node))
    
    else:
        # Show help for node command
        embed = create_info_embed("Node Management", 
            f"Manage multi-node infrastructure for {BOT_NAME}")

class HelpView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.current_category = "user"
        # Command categories
        self.command_categories = {
            "user": {
                "name": "👤 User Commands",
                "commands": [
                    (f"{PREFIX}ping", "Check bot latency"),
                    (f"{PREFIX}uptime", "Show host uptime"),
                    (f"{PREFIX}myvps", "List your VPS"),
                    (f"{PREFIX}manage [@user]", "Manage your VPS or another user's VPS (Admin only)"),
                    (f"{PREFIX}share-user @user <vps_number>", "Share VPS access"),
                    (f"{PREFIX}share-ruser @user <vps_number>", "Revoke VPS access"),
                    (f"{PREFIX}manage-shared @owner <vps_number>", "Manage shared VPS"),
                    (f"{PREFIX}invite", "Create a personal invite link for VPS rewards"),
                    (f"{PREFIX}invite-stats", "Show your verified valid invites and unlocked rewards"),
                    (f"{PREFIX}claim", "Choose and claim an unlocked invite VPS reward")
                ]
            },
            "vps": {
                "name": "🖥️ VPS Management",
                "commands": [
                    (f"{PREFIX}myvps", "List your VPS"),
                    (f"{PREFIX}vpsinfo [vps-id]", "Get VPS information by ID"),
                    (f"{PREFIX}vps-stats <vps-id>", "Get VPS resource stats"),
                    (f"{PREFIX}vps-uptime <vps-id>", "Get VPS uptime"),
                    (f"{PREFIX}vps-processes <vps-id>", "List running processes in VPS"),
                    (f"{PREFIX}vps-logs <vps-id> [lines]", "View VPS logs"),
                    (f"{PREFIX}restart-vps <vps-id>", "Restart VPS"),
                    (f"{PREFIX}clone-vps <vps-id> [new_name]", "Clone VPS by ID"),
                    (f"{PREFIX}vps-password <vps-id>", "Get/reset VPS root password"),
                    (f"{PREFIX}vps-network <vps-id>", "Show VPS network configuration"),
                    (f"{PREFIX}status <vps-id>", "Get VPS status (running/stopped)"),
                    (f"{PREFIX}snapshot-create <vps-id> [name]", "Create a VPS snapshot"),
                    (f"{PREFIX}snapshot-list <vps-id>", "List VPS snapshots"),
                    (f"{PREFIX}snapshot-delete <vps-id> <name>", "Delete a VPS snapshot"),
                    (f"{PREFIX}vps-virtualization <vps-id>", "Show LXC/KVM isolation and kernel behavior"),
                    (f"{PREFIX}vps-neofetch <vps-id>", "Show real guest neofetch/fastfetch system information (alias: neofetch)"),
                    (f"{PREFIX}vps-health <vps-id>", "Check VPS health and resources"),
                    (f"{PREFIX}vps-metrics <vps-id>", "Show live guest CPU/load, RAM, disk, network and HTTPS metrics"),
                    (f"{PREFIX}vps-rotate-password <vps-id>", "Rotate root SSH password and send it privately")
                ]
            },
            "ports": {
                "name": "🔌 Port Forwarding",
                "commands": [
                    (f"{PREFIX}ports [add <vps_num> <port> | list | remove <id>]", "Manage port forwards (TCP/UDP)"),
                    (f"{PREFIX}ports-add-user <amount> @user", "Allocate port slots to user (Admin only)"),
                    (f"{PREFIX}ports-remove-user <amount> @user", "Deallocate port slots from user (Admin only)"),
                    (f"{PREFIX}ports-revoke <id>", "Revoke specific port forward (Admin only)")
                ]
            },
            "system": {
                "name": "⚙️ System Commands",
                "commands": [
                    (f"{PREFIX}serverstats", "Server statistics"),
                    (f"{PREFIX}resource-check", "Check and suspend high-usage VPS (Admin only)"),
                    (f"{PREFIX}cpu-monitor <status|enable|disable>", "Resource monitor control (logging only)"),
                    (f"{PREFIX}thresholds", "View resource thresholds"),
                    (f"{PREFIX}set-threshold <cpu> <ram>", "Set resource thresholds (Admin only)"),
                    (f"{PREFIX}set-status <type> <name>", "Set bot status (Admin only)"),
                    (f"{PREFIX}os-list", "List available OS images")
                ]
            },
            "ai": {
                "name": "🧠 AI Recovery",
                "commands": [
                    (f"{PREFIX}ai-status", "Show autonomous VPS health/recovery agent status (Admin only)"),
                    (f"{PREFIX}ai-agent <on|off|status>", "Enable/disable autonomous recovery (Admin only)"),
                    (f"{PREFIX}ai-fix <vps-id>", "Run immediate safe VPS diagnosis and repair (Admin only)"),
                    (f"{PREFIX}ai-check", "Run read-only host/bot health check (Admin only)")
                ],
                "admin_only": True
            },
            "nodes": {
                "name": "🌐 Node Management",
                "commands": [
                    (f"{PREFIX}node create", "Create a new node (Admin only)"),
                    (f"{PREFIX}node default <id>", "Set or show the default deployment node (Admin only)"),
                    (f"{PREFIX}node auto-default", "Find and set the fastest healthy remote node as default (Admin only)"),
                    (f"{PREFIX}node list", "List all nodes (Admin only)"),
                    (f"{PREFIX}node status <id>", "Check node status (Admin only)"),
                    (f"{PREFIX}node edit <id>", "Edit node details or convert Local↔Dynamic (Admin only)"),
                    (f"{PREFIX}node set-slots <id> <slots>", "Set node VPS slot capacity (Admin only)"),
                    (f"{PREFIX}node regen-key <id>", "Regenerate API key for Dynamic node (Admin only)"),
                    (f"{PREFIX}node delete <id>", "Delete a node (Admin only)"),
                    (f"{PREFIX}node migrate <from> <to>", "Migrate VPS between nodes (Admin only)"),
                    (f"{PREFIX}lxc-list [node_id]", "List LXC containers on node (Admin only)")
                ],
                "admin_only": True
            },
            "bot": {
                "name": "🤖 Bot Control",
                "commands": [
                    (f"{PREFIX}ping", "Check bot latency"),
                    (f"{PREFIX}uptime", "Show host uptime"),
                    (f"{PREFIX}help", "Show this help menu"),
                    (f"{PREFIX}set-status <type> <name>", "Set bot status (Admin only)"),
                    (f"{PREFIX}prefix", "Show current command prefix"),
                    (f"{PREFIX}set-prefix <prefix>", "Change command prefix (Admin only)"),
                    (f"{PREFIX}ai <problem>", "AI diagnosis and safe repair guidance")
                ]
            },
            "admin": {
                "name": "🛡️ Admin Commands",
                "commands": [
                    (f"{PREFIX}lxc-list", "List all LXC containers"),
                    (f"{PREFIX}create <ram_gb> <cpu_cores> <disk_gb> @user [expiry_days]", "Create VPS with OS selection (optional expiry in days)"),
                    (f"{PREFIX}delete-vps @user <vps-id> [reason]", "Delete user's VPS by ID"),
                    (f"{PREFIX}add-resources <vps-id> [ram] [cpu] [disk]", "Add resources to VPS"),
                    (f"{PREFIX}resize-vps <vps-id> [ram] [cpu] [disk]", "Resize VPS resources"),
                    (f"{PREFIX}suspend-vps <vps-id> [reason]", "Suspend VPS by ID"),
                    (f"{PREFIX}unsuspend-vps <vps-id>", "Unsuspend VPS by ID"),
                    (f"{PREFIX}suspension-logs [vps-id]", "View suspension logs"),
                    (f"{PREFIX}whitelist-vps <vps-id> <add|remove>", "Whitelist VPS from auto-suspend"),
                    (f"{PREFIX}userinfo @user", "User information"),
                    (f"{PREFIX}list-all", "List all VPS"),
                    (f"{PREFIX}exec <vps-id> <command>", "Execute command in VPS"),
                    (f"{PREFIX}stop-vps-all", "Stop all VPS on system"),
                    (f"{PREFIX}migrate-vps <vps-id> <pool>", "Migrate VPS to different storage pool"),
                    (f"{PREFIX}vps-network <vps-id> <action> [value]", "Network management and configuration"),
                    (f"{PREFIX}apply-permissions <vps-id>", "Apply Docker-ready permissions to VPS"),
                    (f"{PREFIX}vps-password <vps-id>", "Get/reset VPS password by ID"),
                    (f"{PREFIX}node-check <node_id>", "Check node health and status"),
                    (f"{PREFIX}node-health [node_id]", "Run a deeper bounded node health check"),
                    (f"{PREFIX}status <vps-id>", "Get VPS status"),
                    (f"{PREFIX}status-summary", "Get summary of all VPS status"),
                    (f"{PREFIX}repair-ports <container-name>", "Repair port forwarding configuration"),
                    (f"{PREFIX}resource-check", "Check and suspend high-usage VPS"),
                    (f"{PREFIX}vps-audit", "Audit database against actual LXC instances"),
                    (f"{PREFIX}vps-sync", "Synchronize stored VPS status with LXC"),
                    (f"{PREFIX}vps-security <vps-id>", "Inspect VPS security/resource configuration"),
                    (f"{PREFIX}deploy-status", "Show deployment policy and resources"),
                    (f"{PREFIX}invite-rewards", "List all invite VPS reward tiers"),
                    (f"{PREFIX}invite-reward-add <invites> <ram> <cpu> <disk> [name]", "Add a custom invite reward tier"),
                    (f"{PREFIX}invite-reward-edit <invites> <ram> <cpu> <disk> [name]", "Edit an invite reward tier"),
                    (f"{PREFIX}invite-reward-update <old> <new> <ram> <cpu> <disk> [name]", "Change threshold and resources of a reward tier"),
                    (f"{PREFIX}invite-reward-remove <invites>", "Remove an invite reward tier"),
                    (f"{PREFIX}invite-reward-toggle <invites> <on|off>", "Enable/disable an invite reward tier"),
                    (f"{PREFIX}invite-sync", "Refresh Discord invite counters"),
                    (f"{PREFIX}invite-audit @user", "Audit a user's tracked referrals and reward claims"),
                    (f"{PREFIX}node-capabilities [node_id]", "Check LXC/KVM host capabilities"),
                    (f"{PREFIX}vps-autostart <vps-id> <on|off>", "Configure VPS boot autostart"),
                    (f"{PREFIX}kvm-list", "List KVM virtual machines"),
                    (f"{PREFIX}os-list", "List configured OS images"),
                    (f"{PREFIX}docker-fix <vps-id>", "Prepare an existing LXC VPS for nested Docker"),
                    (f"{PREFIX}vps-network-test <vps-id>", "Diagnose VPS network and SSH connectivity"),
                    (f"{PREFIX}kvm-repair", "Repair local KVM/libvirt/QEMU prerequisites"),
                    (f"{PREFIX}kvm-selftest", "Non-destructive KVM/libvirt readiness test"),
                    (f"{PREFIX}kvm-network-repair <vps-id|name>", "Repair and diagnose KVM IPv4/DHCP/internet"),
                    (f"{PREFIX}cloudflare-fix <vps-id-or-name>", "Install/repair cloudflared in LXC VPS"),
                    (f"{PREFIX}vps-diagnostics <vps-id-or-name>", "Read-only VPS health, network, SSH and Cloudflare diagnostics"),
                    (f"{PREFIX}vps-repair <vps-id-or-name> [component]", "Repair common guest-side SSH, Cloudflare, SSHX and Docker/nesting issues"),
                    (f"{PREFIX}cloudflare-status <vps-id>", "Check cloudflared and internet status"),
                    (f"{PREFIX}ptero-status", "Check Pterodactyl Application API"),
                    (f"{PREFIX}ptero-nodes", "List Pterodactyl Wings nodes"),
                    (f"{PREFIX}ptero-servers", "List Pterodactyl servers"),
                    (f"{PREFIX}ptero-create <name> <user> <egg> <allocation> [ram] [disk] [cpu]", "Create a Pterodactyl server")
                ],
                "admin_only": True
            },
            "expiration": {
                "name": "⏰ VPS Expiration",
                "commands": [
                    (f"{PREFIX}set-expiration <vps-id> <days>", "Set VPS expiration date (Admin only)"),
                    (f"{PREFIX}renew-vps <vps-id> [days]", "Renew VPS expiration (Admin only)"),
                    (f"{PREFIX}vps-expiration [vps-id]", "Check VPS expiration status (Admin only)")
                ],
                "admin_only": True
            },
            "maintenance": {
                "name": "🔧 Maintenance & Monitoring",
                "commands": [
                    (f"{PREFIX}cpu-monitor <status|enable|disable>", "Resource monitor control (logging only)"),
                    (f"{PREFIX}backup-db", "Backup VPS database (Admin only)"),
                    (f"{PREFIX}repair-ports <container-name>", "Repair port forwarding configuration (Admin only)"),
                    (f"{PREFIX}node-check <node_id>", "Check node health and status (Admin only)"),
                    (f"{PREFIX}resource-check", "Check and suspend high-usage VPS (Admin only)")
                ],
                "admin_only": True
            },
            "main_admin": {
                "name": "👑 Main Admin Commands",
                "commands": [
                    (f"{PREFIX}admin-add @user", "Add admin"),
                    (f"{PREFIX}admin-remove @user", "Remove admin"),
                    (f"{PREFIX}admin-list", "List admins")
                ],
                "admin_only": True,
                "main_admin_only": True
            }
        }
        self.update_select()
        self.update_embed()
        self.add_item(self.select)

    def update_select(self):
        """Update the category selection dropdown based on user permissions"""
        self.select = discord.ui.Select(placeholder="Select Category", options=[])
        user_id = str(self.ctx.author.id)
        is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
        is_main_admin_user = user_id == str(MAIN_ADMIN_ID)
       
        # Add all categories that user has access to
        options = []
        # Always show basic categories
        basic_categories = ["user", "vps", "ports", "system", "bot"]
        for category in basic_categories:
            options.append(discord.SelectOption(
                label=self.command_categories[category]["name"],
                value=category,
                emoji=self.get_category_emoji(category)
            ))
       
        # Add nodes category if admin
        if is_admin_user:
            options.append(discord.SelectOption(
                label=self.command_categories["nodes"]["name"],
                value="nodes",
                emoji=self.get_category_emoji("nodes")
            ))
            options.append(discord.SelectOption(
                label=self.command_categories["ai"]["name"],
                value="ai",
                emoji=self.get_category_emoji("ai")
            ))
       
        # Add admin categories if user has permissions
        if is_admin_user:
            options.append(discord.SelectOption(
                label=self.command_categories["admin"]["name"],
                value="admin",
                emoji=self.get_category_emoji("admin")
            ))
            options.append(discord.SelectOption(
                label=self.command_categories["expiration"]["name"],
                value="expiration",
                emoji=self.get_category_emoji("expiration")
            ))
            options.append(discord.SelectOption(
                label=self.command_categories["maintenance"]["name"],
                value="maintenance",
                emoji=self.get_category_emoji("maintenance")
            ))
       
        if is_main_admin_user:
            options.append(discord.SelectOption(
                label=self.command_categories["main_admin"]["name"],
                value="main_admin",
                emoji=self.get_category_emoji("main_admin")
            ))
       
        self.select.options = options
        self.select.callback = self.select_callback
   
    async def select_callback(self, interaction: discord.Interaction):
        """Handle category selection"""
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        
        self.current_category = interaction.data['values'][0]
        self.update_embed()
        await interaction.response.edit_message(embed=self.embed, view=self)

    def get_category_emoji(self, category):
        """Get emoji for each category"""
        emojis = {
            "user": "👤",
            "vps": "🖥️",
            "ports": "🔌",
            "system": "⚙️",
            "bot": "🤖",
            "nodes": "🌐",
            "admin": "🛡️",
            "expiration": "⏰",
            "maintenance": "🔧",
            "main_admin": "👑",
            "ai": "🧠"
        }
        return emojis.get(category, "📁")
   
    def update_embed(self):
        """Update the embed based on current category and user permissions"""
        category_data = self.command_categories[self.current_category]
        # Create embed with category-specific styling
        colors = {
            "user": 0x3498db, # Blue
            "vps": 0x2ecc71, # Green
            "ports": 0xe74c3c, # Red
            "system": 0xf39c12, # Orange
            "bot": 0x9b59b6, # Purple
            "nodes": 0x1abc9c, # Teal
            "admin": 0xe67e22, # Carrot
            "expiration": 0xff6b6b, # Coral red for expiration
            "maintenance": 0x34495e, # Dark gray for maintenance
            "main_admin": 0xf1c40f, # Yellow
            "ai": 0x5865f2
        }
        color = colors.get(self.current_category, 0x1a1a1a)
       
        title = f"📚 {BOT_NAME} Command Help - {category_data['name']}"
        description = f"**{category_data['name']}**\nUse the dropdown below to switch categories."
       
        # Add helpful tips based on category
        tips = {
            "user": f"Tip: Use `{PREFIX}myvps` to see all your VPS and `{PREFIX}manage` to control them.",
            "vps": f"Tip: Use `{PREFIX}manage` to control your VPS from Discord.",
            "ports": "Tip: Port forwards work for both TCP and UDP protocols.",
            "system": "Tip: Set thresholds to monitor resource usage across nodes.",
            "nodes": f"Tip: Use `{PREFIX}node list` to see all available nodes and their status.",
            "admin": f"Tip: Always check `{PREFIX}userinfo @user` before modifying VPS.",
            "expiration": "Tip: VPS are automatically suspended when they expire. Renew them to unsuspend.",
            "maintenance": f"Tip: Use `{PREFIX}backup-db` regularly to backup your VPS database.",
            "main_admin": "Tip: Be careful when adding/removing admin privileges."
        }
       
        if self.current_category in tips:
            description += f"\n\n💡 {tips[self.current_category]}"
       
        self.embed = create_embed(title, description, color)
       
        # Add commands to embed without exceeding Discord's 1024-character field limit.
        command_lines = [f"**{cmd}** - {desc}" for cmd, desc in category_data["commands"]]
        chunks, current = [], ""
        for line in command_lines:
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) > 1000:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)
        for idx, chunk in enumerate(chunks, 1):
            add_field(self.embed, "Commands" if len(chunks) == 1 else f"Commands ({idx}/{len(chunks)})", chunk, False)
       
        # Add appropriate footer based on category
        footers = {
            "user": f"{BOT_NAME} VPS Manager • User Commands • Need help? Contact admin",
            "vps": f"{BOT_NAME} VPS Manager • VPS Management • Cloning",
            "ports": f"{BOT_NAME} VPS Manager • Port Forwarding • TCP/UDP Support",
            "system": f"{BOT_NAME} VPS Manager • System Monitoring • Resource Management",
            "nodes": f"{BOT_NAME} VPS Manager • Multi-Node Management • Distributed Infrastructure",
            "bot": f"{BOT_NAME} VPS Manager • Bot Control • Status Management",
            "admin": f"{BOT_NAME} VPS Manager • Admin Panel • Restricted Access",
            "expiration": f"{BOT_NAME} VPS Manager • VPS Expiration • Auto-Suspension",
            "maintenance": f"{BOT_NAME} VPS Manager • System Maintenance • Database Backup & Repair",
            "main_admin": f"{BOT_NAME} VPS Manager • Main Admin • Full System Control"
        }
       
        self.embed.set_footer(text=footers.get(self.current_category, f"{BOT_NAME} VPS Manager"))


@bot.command(name='panel-test')
async def panel_test(ctx, vps_ref: str):
    """Read-only health check for every VPS panel integration."""
    vps = resolve_vps_reference(vps_ref)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'No VPS matches `{vps_ref}`.'))
        return
    uid = str(ctx.author.id)
    if not is_admin_user_id(uid) and str(vps.get('user_id')) != uid:
        await ctx.send(embed=create_error_embed('Access Denied', 'You can only test your own VPS.'))
        return
    name = str(vps['container_name'])
    backend = str(vps.get('backend','lxc')).lower()
    checks=[]
    try:
        if backend == 'kvm':
            caps=_kvm_local_capabilities()
            checks.append(('KVM host', bool(caps.get('ready')), 'libvirt/qemu prerequisites'))
            nets=await wait_for_kvm_network(name, timeout=12)
            checks.append(('Guest IPv4', bool(nets), ', '.join(nets.values()) if nets else 'No DHCP/agent IPv4'))
            try:
                pong=await kvm_guest_exec(name, 'printf PANEL_QGA_OK', timeout=12)
                checks.append(('QEMU Guest Agent', 'PANEL_QGA_OK' in str(pong), 'guest-exec'))
            except Exception as exc:
                checks.append(('QEMU Guest Agent', False, str(exc)[:180]))
        else:
            nets=await get_container_networks(name, int(vps.get('node_id',1)))
            checks.append(('Guest IPv4', bool(nets), ', '.join(nets.values()) if nets else 'No IPv4'))
            try:
                pong=await _panel_guest_exec(vps, 'printf PANEL_EXEC_OK', timeout=12)
                checks.append(('Guest Exec', 'PANEL_EXEC_OK' in str(pong), 'exec path'))
            except Exception as exc:
                checks.append(('Guest Exec', False, str(exc)[:180]))
        try:
            ssh_state=await _panel_guest_exec(vps, "(systemctl is-active ssh 2>/dev/null || systemctl is-active sshd 2>/dev/null || true); ss -lnt 2>/dev/null | grep -E ':(22)\\b' || true", timeout=12)
            checks.append(('SSH', bool(re.search(r'active|:22\\b', str(ssh_state), re.I)), str(ssh_state)[:180]))
        except Exception as exc:
            checks.append(('SSH', False, str(exc)[:180]))
        checks.append(('Tunnel record', bool(vps.get('pinggy_host') and vps.get('pinggy_port')), f"{vps.get('pinggy_host','none')}:{vps.get('pinggy_port','-')}"))
        lines=[]
        for label, ok, detail in checks:
            lines.append(f"{'✅' if ok else '❌'} **{label}:** {detail}")
        passed=sum(1 for _,ok,_ in checks if ok)
        embed=create_success_embed('🧪 VPS Panel Test', f"`{name}` • **{passed}/{len(checks)} checks passed**")
        add_field(embed,'Read-only Checks','\n'.join(lines)[:3800],False)
        add_field(embed,'Panel Features','Reinstall • Start • Stop • Restart • Password • SSH • SSHX • Tunnel • Stats • Delete • AI Health',False)
        await ctx.send(embed=embed)
    except Exception as exc:
        await ctx.send(embed=create_error_embed('Panel Test Failed', str(exc)[:1800]))


@bot.command(name='help')
async def show_help(ctx):
    """Display the interactive help menu"""
    view = HelpView(ctx)
    await ctx.send(embed=view.embed, view=view)


# Command aliases for typos and convenience
@bot.command(name='mangage')
async def manage_typo(ctx):
    await ctx.send(embed=create_info_embed("Command Correction", f"Did you mean `{PREFIX}manage`? Use the correct command."))


@bot.command(name='commands')
async def commands_alias(ctx):
    """Alias for help command"""
    await show_help(ctx)


@bot.command(name='stats')
async def stats_alias(ctx):
    if str(ctx.author.id) == str(MAIN_ADMIN_ID) or str(ctx.author.id) in admin_data.get("admins", []):
        await server_stats(ctx)
    else:
        await ctx.send(embed=create_error_embed("Access Denied", "This command requires admin privileges."))


@bot.command(name='info')
async def info_alias(ctx, user: discord.Member = None):
    if str(ctx.author.id) == str(MAIN_ADMIN_ID) or str(ctx.author.id) in admin_data.get("admins", []):
        if user:
            await user_info(ctx, user)
        else:
            await ctx.send(embed=create_error_embed("Usage", f"Please specify a user: `{PREFIX}info @user`"))
    else:
        await ctx.send(embed=create_error_embed("Access Denied", "This command requires admin privileges."))

# ═══════════════════════════════════════════════════════════════════
# !deploy — Self-service VPS deployment
# ═══════════════════════════════════════════════════════════════════

# Track in-flight deploys to prevent duplicate submissions
_deploying_users: set = set()


class DeployOSView(discord.ui.View):
    """OS selection dropdown shown after the user clicks Create in !deploy."""
    def __init__(self, user: discord.Member, ctx, node_id: int):
        super().__init__(timeout=120)
        self.user = user
        self.ctx = ctx
        self.node_id = node_id
        options = [discord.SelectOption(label=o["label"], value=o["value"]) for o in OS_OPTIONS]
        self.select = discord.ui.Select(placeholder="Select OS for your VPS", options=options)
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("Access Denied", "Only you can select the OS."), ephemeral=True)
            return
        os_value = self.select.values[0]
        os_label = next((o["label"] for o in OS_OPTIONS if o["value"] == os_value), os_value)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            embed=create_info_embed("🚀 Deploying VPS", f"Deploying **{os_label}**… this takes 1-3 minutes.\n\nThe image and storage pool will be checked before creation."))
        try:
            await _do_free_deploy(self.ctx, self.user, os_value, self.node_id)
        finally:
            _deploying_users.discard(str(self.user.id))

    async def on_timeout(self):
        _deploying_users.discard(str(self.user.id))


class DeployConfirmView(discord.ui.View):
    """Confirm/Cancel buttons shown by !deploy with resource info."""
    def __init__(self, user: discord.Member, ctx, node_id: int):
        super().__init__(timeout=120)
        self.user = user
        self.ctx = ctx
        self.node_id = node_id

    async def _check_author(self, interaction: discord.Interaction) -> bool:
        if not is_admin_user_id(str(interaction.user.id)) and not is_free_deploy_enabled():
            await interaction.response.send_message(
                embed=create_error_embed("Free Deploy Disabled", "Free VPS deployment is currently disabled by an administrator."), ephemeral=True)
            return False
        if str(interaction.user.id) != str(self.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("Access Denied", "Only you can confirm this."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Create VPS", style=discord.ButtonStyle.success)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_author(interaction):
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        # !deploy already defines DEPLOY_RAM/DEPLOY_CPU/DEPLOY_DISK.
        # Never ask the operator to select CPU a second time.
        free_cfg = get_free_deploy_config()
        backend_view = BackendSelectView(
            free_cfg['ram'], free_cfg['cpu'], free_cfg['disk'], self.user, self.ctx,
            self.node_id, DEFAULT_VPS_EXPIRATION_DAYS, deploy_mode=True
        )
        embed = create_info_embed(
            "🧩 Select Virtualization",
            f"**RAM:** {free_cfg['ram']}GB  •  **CPU:** {free_cfg['cpu']} vCPU  •  **Disk:** {free_cfg['disk']}GB\n\n"
            "CPU allocation is fixed by the deploy configuration. If you choose KVM, you can select the processor model next."
        )
        await interaction.followup.send(embed=embed, view=backend_view)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_author(interaction):
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(embed=create_info_embed("Cancelled", "VPS deployment cancelled."))
        _deploying_users.discard(str(self.user.id))

    async def on_timeout(self):
        _deploying_users.discard(str(self.user.id))

async def start_pinggy_tunnel(container_name: str, node_id: int) -> Optional[str]:
    """Compatibility entry point; all callers use the durable Pinggy supervisor."""
    if not PINGGY_ENABLED:
        return None
    info = await start_pinggy_session(container_name, node_id)
    if not info:
        return None
    return str(info.get('url') or f"tcp://{info.get('host')}:{info.get('port')}")


def parse_pinggy_url(raw_url: str):
    """Parse pinggy tunnel URL into (host, port) tuple"""
    try:
        # Find tcp:// anywhere in the string
        import re
        match = re.search(r'tcp://([^\s:]+):(\d+)', raw_url)
        if match:
            return match.group(1), match.group(2)
        return None, None
    except Exception:
        return None, None


def resolve_pinggy_ipv4(host: str):
    """Resolve Pinggy's current shared IPv4 ingress address(es) for display.

    These are Pinggy provider edge IPs, not dedicated IPs assigned to the VPS.
    Keep using the provider hostname in the SSH command.
    """
    import socket
    try:
        rows = socket.getaddrinfo(str(host), None, socket.AF_INET, socket.SOCK_STREAM)
        return list(dict.fromkeys(row[4][0] for row in rows))
    except (OSError, ValueError, TypeError):
        return []
    
async def _do_free_deploy(ctx, user: discord.Member, os_version: str, node_id: int,
                           ram_gb: Optional[int] = None, cpu_cores: Optional[int] = None,
                           disk_gb: Optional[int] = None, provision_source: str = "admin",
                           reward_tier: Optional[int] = None):
    """Core deployment logic. Normal !deploy remains admin-only; invite rewards
    pass an explicit resource set and provision source."""
    is_reward = str(provision_source).lower() == "invite_reward"
    is_admin = is_admin_user_id(str(user.id))
    if not is_reward and not is_admin and not is_free_deploy_enabled():
        raise PermissionError("Free VPS deployment is disabled by an administrator.")
    free_cfg = get_free_deploy_config()
    if is_admin:
        # Administrators are intentionally unlimited by bot policy: no per-user
        # VPS count and no global free-deploy slot limit. Physical host/node
        # capacity guards still apply before every deployment.
        pass
    elif not is_reward:
        user_vps_count = sum(len(items) for uid, items in vps_data.items() if str(uid) == str(user.id))
        if free_cfg['user_limit'] > 0 and user_vps_count >= free_cfg['user_limit']:
            raise PermissionError(f"Free deploy limit reached: maximum {free_cfg['user_limit']} VPS per user.")
        total_vps, *_ = get_slot_stats_deploy()
        if DEPLOY_SLOT > 0 and total_vps >= DEPLOY_SLOT:
            raise PermissionError(f"Free deploy capacity is full ({DEPLOY_SLOT} VPS). Please contact an administrator.")
    ram_gb = int(ram_gb if ram_gb is not None else free_cfg['ram'])
    cpu_cores = int(cpu_cores if cpu_cores is not None else free_cfg['cpu'])
    disk_gb = int(disk_gb if disk_gb is not None else free_cfg['disk'])
    if ram_gb <= 0 or cpu_cores <= 0 or disk_gb <= 0:
        raise ValueError("Deployment resources must be positive.")
    user_id = str(user.id)
    container_name = None
    created = False
    persisted = False
    try:
        # Allocate a name that is unique in BOTH the database and the real LXC node.
        # A previous failed deployment can leave an LXC container behind without a DB row.
        container_name, global_vps_id = await allocate_unique_container_name(user.name, node_id)
        ram_mb = ram_gb * 1024
        await create_instance_from_image(container_name, os_version, node_id)
        created = True
        await execute_lxc(container_name, f"config set {container_name} limits.memory {ram_mb}MB", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} limits.cpu {cpu_cores}", node_id=node_id)
        await execute_lxc(container_name, f"config device set {container_name} root size={disk_gb}GB", node_id=node_id)
        await apply_lxc_config(container_name, node_id)
        await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
        await apply_internal_permissions(container_name, node_id)

        root_password = generate_strong_password()
        await configure_ssh(container_name, node_id, root_password)

        config_str = f"{ram_gb}GB RAM / {cpu_cores} CPU / {disk_gb}GB Disk"
        expiration_date = (datetime.now() + timedelta(days=DEFAULT_VPS_EXPIRATION_DAYS)).isoformat()

        # Start Pinggy tunnel
        pinggy_raw = await start_pinggy_tunnel(container_name, node_id)
        pinggy_host, pinggy_port = parse_pinggy_url(pinggy_raw) if pinggy_raw else (None, None)

        vps_info = {
            "container_name": container_name,
            "node_id": node_id,
            "ram": f"{ram_gb}GB",
            "cpu": str(cpu_cores),
            "storage": f"{disk_gb}GB",
            "config": config_str,
            "os_version": os_version,
            "status": "running",
            "suspended": False,
            "whitelisted": False,
            "suspension_history": [],
            "created_at": datetime.now().isoformat(),
            "shared_with": [],
            "expiration_date": expiration_date,
            "root_password": root_password,
            "pinggy_host": pinggy_host,
            "pinggy_port": pinggy_port,
            "id": global_vps_id,
            "provision_source": provision_source,
            "reward_tier": reward_tier,
        }
        if user_id not in vps_data:
            vps_data[user_id] = []
        vps_data[user_id].append(vps_info)
        save_vps_data_immediate()
        if not verify_vps_persisted(vps_info):
            raise RuntimeError(f"VPS {container_name} was created but could not be persisted to SQLite.")
        persisted = True

        # Keep Cloudflare setup separate from core provisioning. A Cloudflare
        # failure must not destroy a healthy VPS. The client is installed
        # automatically for LXC guests when enabled; a configured tunnel token
        # additionally starts the managed Tunnel service.
        cloudflare_info = {'enabled': bool(CLOUDFLARE_INSTALL_ENABLED), 'installed': False, 'tunnel_active': False}
        if CLOUDFLARE_INSTALL_ENABLED:
            try:
                cf_out = await asyncio.wait_for(
                    _safe_cloudflare_install(container_name, node_id), timeout=300
                )
                cloudflare_info.update({
                    'installed': 'CLOUDFLARED_INSTALLED=YES' in (cf_out or '') or 'CLOUDFLARED_SERVICE=ACTIVE' in (cf_out or ''),
                    'tunnel_active': 'CLOUDFLARED_SERVICE=ACTIVE' in (cf_out or ''),
                    'checked_at': datetime.now().isoformat(),
                    'details': (cf_out or '')[-1200:]
                })
            except Exception as cf_exc:
                logger.warning('Cloudflare post-deploy setup failed for %s: %s', container_name, cf_exc)
                cloudflare_info.update({'error': str(cf_exc)[:1000], 'checked_at': datetime.now().isoformat()})
            vps_info['cloudflare'] = cloudflare_info
            save_vps_data_immediate()

        if ctx.guild:
            vps_role = await get_or_create_vps_role(ctx.guild)
            if vps_role:
                try:
                    await user.add_roles(vps_role, reason="VPS deployed via !deploy")
                except discord.Forbidden:
                    pass

        # DM credentials to user
        dm_embed = create_success_embed("🎁 Invite Reward VPS Deployed!" if is_reward else "🎉 VPS Deployed!", "Your invite reward VPS is ready!" if is_reward else "Your free VPS is ready!")
        dm_embed.add_field(name="📊 Details", value=(
            f"**Container:** `{container_name}`\n"
            f"**OS:** {os_version}\n"
            f"**Config:** {config_str}\n"
            f"**Expires:** {(datetime.now() + timedelta(days=DEFAULT_VPS_EXPIRATION_DAYS)).strftime('%Y-%m-%d')}"
        ), inline=False)

        if pinggy_host and pinggy_port:
            ssh_info = (
                f"**SSH Command:**\n"
                f"`ssh root@{pinggy_host} -p {pinggy_port}`\n\n"
                f"**Username:** `root`\n"
                f"**Password:** `{root_password}`\n\n"
                f"🔒 Save this password!\n"
                f"⚠️ If tunnel disconnects, use `{PREFIX}manage` → **🔄 Reconnect Tunnel**."
            )
        else:
            ssh_info = (
                f"⚠️ Pinggy tunnel could not start.\n"
                f"Use `{PREFIX}manage` → **🔄 Reconnect Tunnel** to start it.\n\n"
                f"**Username:** `root`\n"
                f"**Password:** `{root_password}`\n\n"
                f"🔒 Save this password!"
            )
        dm_embed.add_field(name="🔐 SSH Access", value=ssh_info, inline=False)
        if CLOUDFLARE_INSTALL_ENABLED:
            cf = cloudflare_info
            if cf.get('tunnel_active'):
                dm_embed.add_field(name="☁️ Cloudflare", value="✅ cloudflared installed and managed Tunnel service is active.", inline=False)
            elif cf.get('installed'):
                dm_embed.add_field(name="☁️ Cloudflare", value="✅ cloudflared client installed. A tunnel token/hostname route is still required to publish a domain.", inline=False)
            else:
                dm_embed.add_field(name="☁️ Cloudflare", value="⚠️ Automatic cloudflared setup needs attention. The VPS deployment itself completed.", inline=False)

        try:
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        node = get_node(node_id)
        pub_embed = create_success_embed("✅ VPS Deployed!", f"{user.mention} your VPS is ready! Check your **DMs** for SSH credentials.")
        pub_embed.add_field(name="Container", value=f"`{container_name}`", inline=True)
        pub_embed.add_field(name="OS", value=os_version, inline=True)
        pub_embed.add_field(name="Node", value=node['name'] if node else "Unknown", inline=True)
        if is_reward:
            pub_embed.add_field(
                name="🎁 Invite Reward",
                value=f"Claimed with **{reward_tier} valid invites**. This VPS is permanently marked as an invite reward.",
                inline=False
            )
        if CLOUDFLARE_INSTALL_ENABLED:
            cf = cloudflare_info
            if cf.get('tunnel_active'):
                cf_text = "✅ cloudflared installed + Tunnel service active"
            elif cf.get('installed'):
                cf_text = "✅ cloudflared installed; Tunnel token/service not active"
            else:
                cf_text = "⚠️ cloudflared setup needs attention; VPS itself is healthy"
            pub_embed.add_field(name="☁️ Cloudflare", value=cf_text, inline=False)
        if pinggy_host and pinggy_port:
            pub_embed.add_field(
                name="🌐 SSH Tunnel",
                value=f"`ssh root@{pinggy_host} -p {pinggy_port}`",
                inline=False
            )
        await ctx.send(embed=pub_embed)
        return vps_info

    except Exception as e:
        logger.exception("!deploy failed for %s", user)
        # Never leave half-created containers behind after a failed deployment.
        if created and not persisted and container_name:
            try:
                await safe_delete_instance(container_name, node_id)
                logger.info("Cleaned up partial deployment container %s", container_name)
            except Exception as cleanup_error:
                logger.error("Failed to clean up partial container %s: %s", container_name, cleanup_error)
        await ctx.send(embed=create_error_embed("Deploy Failed", str(e)))
        return None
    finally:
        _deploying_users.discard(str(user.id))
# ═══════════════════════════════════════════════════════════════════════════
# INVITE VPS REWARD SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

_invite_sync_locks: Dict[int, asyncio.Lock] = {}

def _invite_lock(guild_id: int) -> asyncio.Lock:
    lock = _invite_sync_locks.get(int(guild_id))
    if lock is None:
        lock = asyncio.Lock()
        _invite_sync_locks[int(guild_id)] = lock
    return lock

def get_invite_rewards(include_disabled: bool = False) -> List[Dict[str, Any]]:
    conn = get_db()
    try:
        sql = "SELECT * FROM invite_rewards"
        if not include_disabled:
            sql += " WHERE enabled=1"
        sql += " ORDER BY min_invites ASC"
        return [dict(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()

def get_invite_reward(min_invites: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM invite_rewards WHERE min_invites=?", (int(min_invites),)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

async def sync_guild_invites(guild: discord.Guild) -> bool:
    try:
        invites = await guild.invites()
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warning("Cannot read invites for guild %s: %s", guild.id, exc)
        return False
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        codes = set()
        for inv in invites:
            codes.add(inv.code)
            conn.execute(
                '''INSERT INTO invite_cache
                   (guild_id, invite_code, inviter_id, uses, max_uses, channel_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(guild_id, invite_code) DO UPDATE SET
                     inviter_id=excluded.inviter_id, uses=excluded.uses,
                     max_uses=excluded.max_uses, channel_id=excluded.channel_id,
                     updated_at=excluded.updated_at''',
                (str(guild.id), inv.code, str(inv.inviter.id) if inv.inviter else None,
                 int(inv.uses or 0), int(inv.max_uses or 0),
                 str(inv.channel.id) if inv.channel else None, now)
            )
        if codes:
            placeholders = ",".join("?" for _ in codes)
            conn.execute(
                f"DELETE FROM invite_cache WHERE guild_id=? AND invite_code NOT IN ({placeholders})",
                (str(guild.id), *codes)
            )
        else:
            conn.execute("DELETE FROM invite_cache WHERE guild_id=?", (str(guild.id),))
        conn.commit()
        return True
    finally:
        conn.close()

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    guild = member.guild
    async with _invite_lock(guild.id):
        try:
            invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("Invite tracking unavailable for guild %s on join: %s", guild.id, exc)
            return
        conn = get_db()
        try:
            old_rows = {
                r["invite_code"]: dict(r)
                for r in conn.execute("SELECT * FROM invite_cache WHERE guild_id=?", (str(guild.id),)).fetchall()
            }
            increased = []
            now = datetime.now().isoformat()
            for inv in invites:
                old = old_rows.get(inv.code)
                old_uses = int(old["uses"]) if old else 0
                new_uses = int(inv.uses or 0)
                if new_uses > old_uses:
                    increased.append((new_uses - old_uses, inv))
                conn.execute(
                    '''INSERT INTO invite_cache
                       (guild_id, invite_code, inviter_id, uses, max_uses, channel_id, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(guild_id, invite_code) DO UPDATE SET
                         inviter_id=excluded.inviter_id, uses=excluded.uses,
                         max_uses=excluded.max_uses, channel_id=excluded.channel_id,
                         updated_at=excluded.updated_at''',
                    (str(guild.id), inv.code, str(inv.inviter.id) if inv.inviter else None,
                     new_uses, int(inv.max_uses or 0),
                     str(inv.channel.id) if inv.channel else None, now)
                )
            if increased:
                increased.sort(key=lambda x: x[0], reverse=True)
                used = increased[0][1]
                inviter_id = str(used.inviter.id) if used.inviter else None
                if inviter_id and inviter_id != str(member.id):
                    conn.execute(
                        '''INSERT OR IGNORE INTO invite_referrals
                           (guild_id, inviter_id, invitee_id, invite_code, joined_at)
                           VALUES (?, ?, ?, ?, ?)''',
                        (str(guild.id), inviter_id, str(member.id), used.code, now)
                    )
            conn.commit()
        finally:
            conn.close()

@bot.event
async def on_member_remove(member: discord.Member):
    if member.bot:
        return
    conn = get_db()
    try:
        conn.execute(
            "UPDATE invite_referrals SET left_at=? WHERE guild_id=? AND invitee_id=? AND left_at IS NULL",
            (datetime.now().isoformat(), str(member.guild.id), str(member.id))
        )
        conn.commit()
    finally:
        conn.close()

async def get_valid_invite_count(guild: discord.Guild, user_id: int) -> int:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT invitee_id FROM invite_referrals WHERE guild_id=? AND inviter_id=? AND left_at IS NULL ORDER BY joined_at ASC",
            (str(guild.id), str(user_id))
        ).fetchall()
    finally:
        conn.close()
    valid = 0
    stale = []
    for row in rows:
        invitee_id = int(row["invitee_id"])
        member = guild.get_member(invitee_id)
        if member is None:
            try:
                member = await guild.fetch_member(invitee_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        if member and not member.bot and invitee_id != int(user_id):
            valid += 1
        else:
            stale.append(str(invitee_id))
    if stale:
        conn = get_db()
        try:
            conn.executemany(
                "UPDATE invite_referrals SET left_at=? WHERE guild_id=? AND invitee_id=? AND left_at IS NULL",
                [(datetime.now().isoformat(), str(guild.id), x) for x in stale]
            )
            conn.commit()
        finally:
            conn.close()
    return valid

def get_claimed_reward_tiers(guild_id: int, user_id: int) -> set:
    conn = get_db()
    try:
        return {
            int(r["min_invites"])
            for r in conn.execute(
                "SELECT min_invites FROM invite_claims WHERE guild_id=? AND user_id=? AND status='claimed'",
                (str(guild_id), str(user_id))
            ).fetchall()
        }
    finally:
        conn.close()

def reserve_invite_claim(guild_id: int, user_id: int, reward: Dict[str, Any], invite_count: int):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM invite_claims WHERE guild_id=? AND user_id=? AND min_invites=?",
            (str(guild_id), str(user_id), int(reward["min_invites"]))
        ).fetchone()
        if existing:
            row = dict(existing)
            if row["status"] == "claimed":
                conn.rollback()
                return False, "This reward tier has already been claimed."
            try:
                age = datetime.now() - datetime.fromisoformat(row["created_at"])
            except Exception:
                age = timedelta(minutes=999)
            if age < timedelta(minutes=20):
                conn.rollback()
                return False, "A claim for this tier is already being processed."
            conn.execute("DELETE FROM invite_claims WHERE id=?", (row["id"],))
        cur = conn.execute(
            '''INSERT INTO invite_claims
               (guild_id, user_id, min_invites, reward_id, status, invite_count,
                ram_gb, cpu_cores, disk_gb, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)''',
            (str(guild_id), str(user_id), int(reward["min_invites"]), int(reward["id"]),
             int(invite_count), int(reward["ram_gb"]), int(reward["cpu_cores"]),
             int(reward["disk_gb"]), datetime.now().isoformat())
        )
        conn.commit()
        return True, cur.lastrowid
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "This reward is already being claimed."
    finally:
        conn.close()

def finalize_invite_claim(claim_id: int, vps_info: Dict[str, Any]) -> None:
    conn = get_db()
    try:
        conn.execute(
            "UPDATE invite_claims SET status='claimed', vps_id=?, container_name=?, claimed_at=? WHERE id=? AND status='pending'",
            (int(vps_info["id"]), str(vps_info["container_name"]), datetime.now().isoformat(), int(claim_id))
        )
        conn.commit()
    finally:
        conn.close()

def cancel_invite_claim(claim_id: int) -> None:
    conn = get_db()
    try:
        conn.execute("DELETE FROM invite_claims WHERE id=? AND status='pending'", (int(claim_id),))
        conn.commit()
    finally:
        conn.close()

class InviteRewardPlanView(discord.ui.View):
    def __init__(self, user: discord.Member, guild: discord.Guild, valid_count: int, rewards: List[Dict[str, Any]]):
        super().__init__(timeout=180)
        self.user, self.guild, self.valid_count, self.rewards = user, guild, valid_count, rewards
        claimed = get_claimed_reward_tiers(guild.id, user.id)
        options = []
        for reward in rewards[:25]:
            minimum = int(reward["min_invites"])
            if minimum <= valid_count and minimum not in claimed:
                label = f'{reward["name"] or "Invite VPS"} — {reward["ram_gb"]}GB/{reward["cpu_cores"]}C/{reward["disk_gb"]}GB'
                options.append(discord.SelectOption(label=label[:100], value=str(minimum), description=f'{minimum}+ valid invites required'))
        if not options:
            options = [discord.SelectOption(label="No unclaimed plan available", value="none")]
        self.select = discord.ui.Select(placeholder="🎁 Choose your unlocked VPS reward", options=options)
        self.select.callback = self._select
        self.add_item(self.select)

    async def _select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the claimant can choose the reward."), ephemeral=True)
            return
        if self.select.values[0] == "none":
            await interaction.response.send_message(embed=create_error_embed("No Reward", "You do not have an unclaimed unlocked reward tier."), ephemeral=True)
            return
        reward = get_invite_reward(int(self.select.values[0]))
        current = await get_valid_invite_count(self.guild, self.user.id)
        if not reward or not reward["enabled"] or int(reward["min_invites"]) > current:
            await interaction.response.send_message(embed=create_error_embed("Reward Locked", "Your valid invite count no longer unlocks this plan."), ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=create_info_embed(
                "🎁 Confirm Invite VPS",
                f"Verified: **{current} valid invites**.\n\n"
                f"**Plan:** {reward['name'] or 'Invite VPS'}\n"
                f"**RAM:** `{reward['ram_gb']} GB` • **CPU:** `{reward['cpu_cores']} cores` • **Disk:** `{reward['disk_gb']} GB`\n\n"
                "Confirm the exact plan below before any VPS is created."
            ),
            view=InviteRewardConfirmView(self.user, self.guild, current, reward)
        )

class InviteRewardConfirmView(discord.ui.View):
    def __init__(self, user: discord.Member, guild: discord.Guild, valid_count: int, reward: Dict[str, Any]):
        super().__init__(timeout=180)
        self.user, self.guild, self.valid_count, self.reward = user, guild, valid_count, reward

    @discord.ui.button(label="✅ Confirm Reward", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the claimant can confirm."), ephemeral=True)
            return
        current = await get_valid_invite_count(self.guild, self.user.id)
        if current < int(self.reward["min_invites"]):
            await interaction.response.send_message(embed=create_error_embed("Invite Count Changed", f"You now have `{current}` valid invites; this plan needs `{self.reward['min_invites']}`."), ephemeral=True)
            return
        ok, claim_id = reserve_invite_claim(self.guild.id, self.user.id, self.reward, current)
        if not ok:
            await interaction.response.send_message(embed=create_error_embed("Claim Not Available", str(claim_id)), ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            embed=create_info_embed("🧩 Choose OS", "Your reward is confirmed and reserved. Select the OS for your VPS."),
            view=InviteRewardOSView(self.user, self.guild, self.reward, int(claim_id), interaction.channel)
        )

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the claimant can cancel."), ephemeral=True)
            return
        await interaction.response.edit_message(embed=create_info_embed("Cancelled", "Invite reward claim cancelled."), view=None)

class InviteRewardOSView(discord.ui.View):
    def __init__(self, user: discord.Member, guild: discord.Guild, reward: Dict[str, Any], claim_id: int, channel):
        super().__init__(timeout=180)
        self.user, self.guild, self.reward, self.claim_id, self.channel = user, guild, reward, claim_id, channel
        options = [discord.SelectOption(label=o["label"], value=o["value"]) for o in OS_OPTIONS[:25]]
        self.select = discord.ui.Select(placeholder="Select OS for your reward VPS", options=options)
        self.select.callback = self._select
        self.add_item(self.select)

    async def _select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the claimant can select the OS."), ephemeral=True)
            return
        nodes = get_nodes()
        if not nodes:
            cancel_invite_claim(self.claim_id)
            await interaction.response.send_message(embed=create_error_embed("No Node", "No VPS node is available right now."), ephemeral=True)
            return
        node_id = int(nodes[0]["id"])
        os_value = self.select.values[0]
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(embed=create_info_embed(
            "🚀 Invite Reward Deployment",
            f"Deploying `{self.reward['ram_gb']}GB RAM / {self.reward['cpu_cores']} CPU / {self.reward['disk_gb']}GB` reward VPS. Duplicate claims are locked."
        ))
        result = await _do_free_deploy(
            self.channel, self.user, os_value, node_id,
            ram_gb=int(self.reward["ram_gb"]), cpu_cores=int(self.reward["cpu_cores"]),
            disk_gb=int(self.reward["disk_gb"]), provision_source="invite_reward",
            reward_tier=int(self.reward["min_invites"])
        )
        if result:
            finalize_invite_claim(self.claim_id, result)
            await interaction.followup.send(embed=create_success_embed(
                "🎁 Invite VPS Claimed",
                f"{self.user.mention} successfully claimed this VPS using **{self.reward['min_invites']} valid invites**."
            ))
        else:
            cancel_invite_claim(self.claim_id)

    async def on_timeout(self):
        cancel_invite_claim(self.claim_id)

@bot.command(name="invite")
async def invite_cmd(ctx):
    if not ctx.guild:
        await ctx.send(embed=create_error_embed("Server Only", "Use this command inside your Discord server."))
        return
    try:
        inv = await ctx.channel.create_invite(max_age=0, max_uses=0, unique=True, reason=f"AxionHost invite reward for {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=create_error_embed("Permission Missing", "I need **Create Invite** permission in this channel."))
        return
    except discord.HTTPException as exc:
        await ctx.send(embed=create_error_embed("Invite Failed", str(exc)[:1000]))
        return
    conn = get_db()
    try:
        conn.execute(
            '''INSERT INTO invite_cache
               (guild_id, invite_code, inviter_id, uses, max_uses, channel_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, invite_code) DO UPDATE SET
                 inviter_id=excluded.inviter_id, uses=excluded.uses,
                 max_uses=excluded.max_uses, channel_id=excluded.channel_id, updated_at=excluded.updated_at''',
            (str(ctx.guild.id), inv.code, str(ctx.author.id), int(inv.uses or 0),
             int(inv.max_uses or 0), str(ctx.channel.id), datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()
    await ctx.send(embed=create_success_embed(
        "🔗 Your Invite", f"Share this invite with new members:\n`{inv.url}`\n\n"
        "Only tracked members who remain in this server count as valid invites."
    ))

@bot.command(name="invite-stats")
async def invite_stats_cmd(ctx):
    if not ctx.guild:
        await ctx.send(embed=create_error_embed("Server Only", "Use this command inside your Discord server."))
        return
    count = await get_valid_invite_count(ctx.guild, ctx.author.id)
    claimed = get_claimed_reward_tiers(ctx.guild.id, ctx.author.id)
    rewards = get_invite_rewards()
    unlocked = [str(r["min_invites"]) for r in rewards if int(r["min_invites"]) <= count and int(r["min_invites"]) not in claimed]
    await ctx.send(embed=create_info_embed(
        "🎁 Invite Reward Status",
        f"**Valid invites:** `{count}`\n"
        f"**Claimed tiers:** `{', '.join(map(str, sorted(claimed))) or 'None'}`\n"
        f"**Unlocked:** `{', '.join(unlocked) or 'None'}`\n\nUse `{PREFIX}claim` to choose a reward."
    ))

@bot.command(name="claim")
async def claim_cmd(ctx):
    if not ctx.guild:
        await ctx.send(embed=create_error_embed("Server Only", "Invite VPS rewards can only be claimed inside the server."))
        return
    async with _invite_lock(ctx.guild.id):
        await sync_guild_invites(ctx.guild)
        valid_count = await get_valid_invite_count(ctx.guild, ctx.author.id)
    rewards = get_invite_rewards()
    claimed = get_claimed_reward_tiers(ctx.guild.id, ctx.author.id)
    unlocked = [r for r in rewards if int(r["min_invites"]) <= valid_count and int(r["min_invites"]) not in claimed]
    if not unlocked:
        minimum = min((int(r["min_invites"]) for r in rewards), default=2)
        await ctx.send(embed=create_error_embed(
            "No Invite Reward Available",
            f"You have **{valid_count} valid invites**. The first reward needs **{minimum}** valid invites, or the available tiers are already claimed."
        ))
        return
    await ctx.send(
        embed=create_info_embed(
            "🎁 Invite VPS Rewards",
            f"Invite verification complete: **{valid_count} valid members**.\nChoose an unlocked, unclaimed plan. You must confirm it before VPS creation."
        ),
        view=InviteRewardPlanView(ctx.author, ctx.guild, valid_count, unlocked)
    )

@bot.command(name="invite-rewards")
@is_admin()
async def invite_rewards_cmd(ctx):
    rewards = get_invite_rewards(include_disabled=True)
    lines = [
        f"`{r['min_invites']}` invites → `{r['ram_gb']}GB / {r['cpu_cores']} CPU / {r['disk_gb']}GB` • "
        f"{'ON' if r['enabled'] else 'OFF'} • ID `{r['id']}` • {r['name'] or 'Unnamed'}"
        for r in rewards
    ]
    await ctx.send(embed=create_info_embed("⚙️ Invite Reward Plans", "\n".join(lines) or "No reward plans configured."))

@bot.command(name="invite-reward-add")
@is_admin()
async def invite_reward_add_cmd(ctx, min_invites: int, ram_gb: int, cpu_cores: int, disk_gb: int, *, name: str = ""):
    if min_invites < 1 or ram_gb < 1 or cpu_cores < 1 or disk_gb < 1:
        await ctx.send(embed=create_error_embed("Invalid Plan", "All values must be positive."))
        return
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        conn.execute(
            '''INSERT INTO invite_rewards
               (min_invites, ram_gb, cpu_cores, disk_gb, name, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)''',
            (min_invites, ram_gb, cpu_cores, disk_gb, name.strip()[:100], now, now)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        await ctx.send(embed=create_error_embed("Already Exists", f"A reward for `{min_invites}` invites already exists. Use edit instead."))
        return
    finally:
        conn.close()
    await ctx.send(embed=create_success_embed("Reward Added", f"`{min_invites}` invites → `{ram_gb}GB / {cpu_cores} CPU / {disk_gb}GB`."))

@bot.command(name="invite-reward-edit")
@is_admin()
async def invite_reward_edit_cmd(ctx, min_invites: int, ram_gb: int, cpu_cores: int, disk_gb: int, *, name: str = ""):
    if min_invites < 1 or ram_gb < 1 or cpu_cores < 1 or disk_gb < 1:
        await ctx.send(embed=create_error_embed("Invalid Plan", "All values must be positive."))
        return
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE invite_rewards SET ram_gb=?, cpu_cores=?, disk_gb=?, name=?, updated_at=? WHERE min_invites=?",
            (ram_gb, cpu_cores, disk_gb, name.strip()[:100], datetime.now().isoformat(), min_invites)
        )
        conn.commit()
        changed = cur.rowcount
    finally:
        conn.close()
    await ctx.send(embed=create_success_embed("Reward Updated", f"Updated `{min_invites}` invite tier." if changed else "That invite tier does not exist."))

@bot.command(name="invite-reward-update")
@is_admin()
async def invite_reward_update_cmd(ctx, old_min_invites: int, new_min_invites: int, ram_gb: int, cpu_cores: int, disk_gb: int, *, name: str = ""):
    if min(old_min_invites, new_min_invites, ram_gb, cpu_cores, disk_gb) < 1:
        await ctx.send(embed=create_error_embed("Invalid Plan", "All values must be positive."))
        return
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE invite_rewards SET min_invites=?, ram_gb=?, cpu_cores=?, disk_gb=?, name=?, updated_at=? WHERE min_invites=?",
            (new_min_invites, ram_gb, cpu_cores, disk_gb, name.strip()[:100],
             datetime.now().isoformat(), old_min_invites)
        )
        conn.commit()
        changed = cur.rowcount
    except sqlite3.IntegrityError:
        conn.rollback()
        await ctx.send(embed=create_error_embed("Already Exists", f"Another reward already uses `{new_min_invites}` invites."))
        return
    finally:
        conn.close()
    await ctx.send(embed=create_success_embed(
        "Reward Updated",
        f"Tier `{old_min_invites}` → `{new_min_invites}` invites, `{ram_gb}GB / {cpu_cores} CPU / {disk_gb}GB`."
        if changed else "The old invite tier does not exist."
    ))

@bot.command(name="invite-reward-remove")
@is_admin()
async def invite_reward_remove_cmd(ctx, min_invites: int):
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM invite_rewards WHERE min_invites=?", (min_invites,))
        conn.commit()
        changed = cur.rowcount
    finally:
        conn.close()
    await ctx.send(embed=create_success_embed("Reward Removed", f"Removed `{min_invites}` invite tier." if changed else "That invite tier does not exist."))

@bot.command(name="invite-reward-toggle")
@is_admin()
async def invite_reward_toggle_cmd(ctx, min_invites: int, state: str):
    state = state.lower()
    if state not in ("on", "off"):
        await ctx.send(embed=create_error_embed("Usage", f"`{PREFIX}invite-reward-toggle <invites> <on|off>`"))
        return
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE invite_rewards SET enabled=?, updated_at=? WHERE min_invites=?",
            (1 if state == "on" else 0, datetime.now().isoformat(), min_invites)
        )
        conn.commit()
        changed = cur.rowcount
    finally:
        conn.close()
    await ctx.send(embed=create_success_embed("Reward Toggled", f"Tier `{min_invites}` is now **{state.upper()}**." if changed else "That invite tier does not exist."))

@bot.command(name="invite-audit")
@is_admin()
async def invite_audit_cmd(ctx, member: discord.Member):
    if not ctx.guild:
        await ctx.send(embed=create_error_embed("Server Only", "Run this inside the target server."))
        return
    count = await get_valid_invite_count(ctx.guild, member.id)
    conn = get_db()
    try:
        rows = conn.execute(
            '''SELECT invitee_id, invite_code, joined_at, left_at
               FROM invite_referrals WHERE guild_id=? AND inviter_id=? ORDER BY joined_at DESC LIMIT 50''',
            (str(ctx.guild.id), str(member.id))
        ).fetchall()
        claimed = conn.execute(
            '''SELECT min_invites, invite_count, ram_gb, cpu_cores, disk_gb, status, vps_id, container_name, claimed_at
               FROM invite_claims WHERE guild_id=? AND user_id=? ORDER BY created_at DESC''',
            (str(ctx.guild.id), str(member.id))
        ).fetchall()
    finally:
        conn.close()
    referral_lines = []
    for row in rows:
        state = "VALID" if not row["left_at"] else "LEFT"
        referral_lines.append(f"`{row['invitee_id']}` • `{state}` • `{row['invite_code'] or 'unknown'}`")
    claim_lines = [
        f"`{r['min_invites']}` invites → `{r['ram_gb']}GB/{r['cpu_cores']}C/{r['disk_gb']}GB` • `{r['status']}` • VPS `{r['vps_id'] or '-'}'"
        for r in claimed
    ]
    await ctx.send(embed=create_info_embed(
        f"🔎 Invite Audit — {member.display_name}",
        f"**Current valid invites:** `{count}`\n\n"
        f"**Tracked referrals:**\n{chr(10).join(referral_lines) or 'None'}\n\n"
        f"**Claims:**\n{chr(10).join(claim_lines) or 'None'}"
    ))

@bot.command(name="invite-sync")
@is_admin()
async def invite_sync_cmd(ctx):
    if not ctx.guild:
        await ctx.send(embed=create_error_embed("Server Only", "Run this inside the target server."))
        return
    ok = await sync_guild_invites(ctx.guild)
    await ctx.send(embed=create_success_embed("Invite Sync", "Discord invite counters refreshed." if ok else "I could not read server invites. Check Manage Server permission."))



def get_slot_stats_deploy():
    total = running = suspended = stopped = expired = 0
    now = datetime.now()
    for user_vps_list in vps_data.values():
        for vps in user_vps_list:
            total += 1
            exp = vps.get('expiration_date')
            if exp and datetime.fromisoformat(exp) < now:
                expired += 1
            if vps.get('suspended'):
                suspended += 1
            elif vps.get('status') == 'running':
                running += 1
            else:
                stopped += 1
    return total, running, suspended, stopped, expired


@bot.command(name='admin-vps-policy', aliases=['admin-unlimited','unlimited-vps'])
@is_admin()
async def admin_vps_policy(ctx):
    """Explain the administrator VPS policy: unlimited count, mandatory safety guards."""
    await ctx.send(embed=create_success_embed(
        '👑 Admin VPS Policy',
        'Administrators have **no bot-imposed per-user or global VPS count limit**.\n\n'
        'Mandatory protections remain active: **host RAM reserve, CPU reserve, disk reserve, LXD name collision checks, deployment concurrency protection, and security baseline**.\n\n'
        'So admins can create unlimited VPS over time, but a deployment is correctly refused when the physical node cannot safely provide the requested resources.'
    ))


@bot.command(name='freeresources', aliases=['free-space', 'freevps-settings'])
async def free_deploy_resources_cmd(ctx, ram_gb: int = None, cpu_cores: int = None, disk_gb: int = None, user_limit: int = None):
    """Admin-only persistent free VPS package editor."""
    if not is_admin_user_id(str(ctx.author.id)):
        await ctx.send(embed=create_error_embed('Access Denied', 'Only configured bot administrators can change free VPS resources.'))
        return
    cfg = get_free_deploy_config()
    if ram_gb is None and cpu_cores is None and disk_gb is None and user_limit is None:
        await ctx.send(embed=create_info_embed('Free VPS Resources',
            f"RAM: `{cfg['ram']}GB`\nCPU: `{cfg['cpu']} cores`\nDisk: `{cfg['disk']}GB`\nPer-user limit: `{cfg['user_limit'] if cfg['user_limit'] > 0 else 'Unlimited'}`\n\n"
            f"Change with `{PREFIX}freeresources <RAM_GB> <CPU> <DISK_GB> [USER_LIMIT]`"))
        return
    if ram_gb is None or cpu_cores is None or disk_gb is None:
        await ctx.send(embed=create_error_embed('Usage', f'Use `{PREFIX}freeresources <RAM_GB> <CPU> <DISK_GB> [USER_LIMIT]`'))
        return
    if not (1 <= ram_gb <= 1024 and 1 <= cpu_cores <= 256 and 1 <= disk_gb <= 100000):
        await ctx.send(embed=create_error_embed('Invalid Resources', 'RAM: 1–1024 GB, CPU: 1–256 cores, Disk: 1–100000 GB.'))
        return
    if user_limit is None:
        user_limit = cfg['user_limit']
    if not 0 <= user_limit <= 1000:
        await ctx.send(embed=create_error_embed('Invalid User Limit', 'Use 1–1000, or 0 for unlimited.'))
        return
    for key, value in {'ram': ram_gb, 'cpu': cpu_cores, 'disk': disk_gb, 'user_limit': user_limit}.items():
        set_setting(f'free_deploy_{key}', str(value))
    await ctx.send(embed=create_success_embed('Free VPS Package Updated',
        f'New deployments: `{ram_gb}GB RAM / {cpu_cores} CPU / {disk_gb}GB Disk`\nPer-user limit: `{user_limit if user_limit > 0 else "Unlimited"}`\nExisting VPS resources are unchanged.'))


@bot.command(name='freedeploy', aliases=['free-deploy', 'freedeploy-settings'])
async def free_deploy_control(ctx, action: str = 'status'):
    """Admin-only persistent switch for public free VPS deployment."""
    if not is_admin_user_id(str(ctx.author.id)):
        await ctx.send(embed=create_error_embed('Access Denied', 'Only configured bot administrators can change free deployment.'))
        return
    action = str(action).strip().lower()
    if action in ('enable', 'on', 'true'):
        set_setting('free_deploy_enabled', '1')
        await ctx.send(embed=create_success_embed('Free Deploy Enabled', f'Public free VPS deployment is now enabled. Users can use `{PREFIX}deploy` within configured limits.'))
    elif action in ('disable', 'off', 'false'):
        set_setting('free_deploy_enabled', '0')
        await ctx.send(embed=create_warning_embed('Free Deploy Disabled', 'Public free VPS deployment is now disabled. Admin deployment and invite-reward claims remain available.'))
    elif action == 'status':
        enabled = is_free_deploy_enabled()
        free_cfg = get_free_deploy_config()
        embed = create_info_embed('Free Deploy Status', f'Public free deployment: **{"ENABLED" if enabled else "DISABLED"}**\nPer-user limit: `{free_cfg["user_limit"] if free_cfg["user_limit"] > 0 else "Unlimited"}`\nGlobal limit: `{DEPLOY_SLOT if DEPLOY_SLOT > 0 else "Unlimited"}`\nResources: `{free_cfg["ram"]}GB RAM / {free_cfg["cpu"]} CPU / {free_cfg["disk"]}GB Disk`')
        await ctx.send(embed=embed)
    else:
        await ctx.send(embed=create_error_embed('Invalid Action', f'Use: `{PREFIX}freedeploy <enable|disable|status>`'))


@bot.command(name='deploy')
async def deploy_cmd(ctx):
    """Deploy a free VPS when enabled; administrators can always deploy."""
    is_admin = is_admin_user_id(str(ctx.author.id))
    if not is_admin and not is_free_deploy_enabled():
        await ctx.send(embed=create_error_embed('Free Deploy Disabled', f'Free VPS deployment is currently disabled. Please contact an administrator.'))
        return
    user_id = str(ctx.author.id)
    if user_id in _deploying_users:
        await ctx.send(embed=create_error_embed("Already Deploying", "You already have a deployment in progress. Please wait."))
        return

    total, running, suspended, stopped, expired = get_slot_stats_deploy()
    free_cfg = get_free_deploy_config()
    if not is_admin:
        user_vps_count = sum(len(items) for uid, items in vps_data.items() if str(uid) == user_id)
        free_cfg = get_free_deploy_config()
        if free_cfg['user_limit'] > 0 and user_vps_count >= free_cfg['user_limit']:
            await ctx.send(embed=create_error_embed('Free Deploy Limit Reached', f'You can have at most `{free_cfg["user_limit"]}` VPS.'))
            return
        if DEPLOY_SLOT > 0 and total >= DEPLOY_SLOT:
            await ctx.send(embed=create_error_embed('Free Deploy Capacity Full', 'The free VPS capacity is currently full. Please try again later.'))
            return
    nodes = get_nodes()
    available_nodes = nodes
    if not available_nodes:
        await ctx.send(embed=create_error_embed("No Nodes Available", "No VPS nodes are configured."))
        return
    node_id = available_nodes[0]['id']
    _deploying_users.add(user_id)

    slot_line = (f"\n> ♾️ **Admin Mode:** no bot-imposed VPS count limit" if is_admin else f"\n> **Your VPS:** `{user_vps_count}/{free_cfg['user_limit'] if free_cfg['user_limit'] > 0 else '∞'}`")
    embed = create_info_embed(
        "🚀 VPS Deployment" if not is_admin else "🚀 Admin VPS Deployment",
        f"> **RAM:** `{free_cfg['ram']}GB`\n"
        f"> **CPU:** `{free_cfg['cpu']}` Cores\n"
        f"> **Disk:** `{free_cfg['disk']}GB`{slot_line}\n"
        f"> **Security:** `{'privileged' if VPS_PRIVILEGED else 'unprivileged'}` / nesting `{'on' if VPS_NESTING else 'off'}`\n\n"
        f"Choose an OS to deploy the VPS."
    )
    view = DeployConfirmView(ctx.author, ctx, node_id)
    await ctx.send(embed=embed, view=view)


# ═══════════════════════════════════════════════════════════════════
# Additional administration / reliability commands
# ═══════════════════════════════════════════════════════════════════

@bot.command(name='os-list')
async def os_list_cmd(ctx):
    """Show all OS images configured for deployment."""
    lines = []
    for item in OS_OPTIONS:
        lines.append(f"• **{item['label']}** — `{item['value']}`")
    embed = create_info_embed("🧩 Available OS Images", "The bot validates an image on the target node before creation.\n\n" + "\n".join(lines))
    add_field(embed, "Security & Virtualization", f"Privileged: `{'ON' if VPS_PRIVILEGED else 'OFF'}`\nNesting: `{'ON' if VPS_NESTING else 'OFF'}`\nSSH hardening: `{'ON' if VPS_HARDEN_SSH else 'OFF'}`\nKVM: `{'ENABLED' if KVM_ENABLED else 'DISABLED'}`\nKVM images: `{len(KVM_SUPPORTED_IMAGES)}`", False)
    await ctx.send(embed=embed)


@bot.command(name='vps-audit')
@is_admin()
async def vps_audit_cmd(ctx):
    """Audit database records against actual LXC instances without deleting anything."""
    await ctx.send(embed=create_info_embed("🔎 VPS Audit", "Scanning database and LXC nodes…"))
    db_by_node = {}
    for user_list in vps_data.values():
        for vps in user_list:
            db_by_node.setdefault(int(vps.get('node_id', 1)), set()).add(vps.get('container_name'))

    findings = []
    for node in get_nodes():
        nid = node['id']
        try:
            raw = await execute_lxc('', 'list --format csv -c n', node_id=nid, timeout=45)
            actual = set()
            for line in str(raw or '').splitlines():
                name = line.strip().strip('"').split(',', 1)[0].strip().strip('"')
                if name:
                    actual.add(name)
            expected = {x for x in db_by_node.get(nid, set()) if x}
            missing = sorted(expected - actual)
            orphan = sorted(actual - expected)
            findings.append(f"**{node['name']}** — DB: `{len(expected)}` / LXC: `{len(actual)}`\nMissing: `{', '.join(missing[:8]) or 'none'}`\nOrphans: `{', '.join(orphan[:8]) or 'none'}`")
        except Exception as exc:
            findings.append(f"**{node['name']}** — ⚠️ audit failed: `{str(exc)[:300]}`")
    embed = create_info_embed("🔎 VPS Audit Results", "\n\n".join(findings) or "No nodes found.")
    add_field(embed, "Safety", "Audit is read-only. No VPS or database record was deleted.", False)
    await ctx.send(embed=embed)


@bot.command(name='vps-sync')
@is_admin()
async def vps_sync_cmd(ctx):
    """Refresh stored VPS status from actual LXC state."""
    changed = 0
    failed = 0
    for user_list in vps_data.values():
        for vps in user_list:
            try:
                raw = await execute_lxc(vps['container_name'], f"info {shlex.quote(vps['container_name'])}", node_id=int(vps.get('node_id', 1)), timeout=30)
                text_out = str(raw or '').lower()
                if vps.get('backend', 'lxc') == 'kvm':
                    new_status = 'running' if ('state: running' in text_out or 'state: running' in text_out.replace(' ', '')) else 'stopped'
                else:
                    new_status = 'running' if 'status: running' in text_out else 'stopped'
                if vps.get('status') != new_status:
                    vps['status'] = new_status
                    changed += 1
            except Exception:
                failed += 1
    save_vps_data_immediate()
    await ctx.send(embed=create_success_embed("🔄 VPS Sync Complete", f"Status changes: `{changed}`\nChecks failed/unreachable: `{failed}`\nDatabase: `{DB_PATH}`"))


@bot.command(name='vps-security')
@is_admin()
async def vps_security_cmd(ctx, vps_id: int):
    """Show security-relevant Incus configuration for a VPS."""
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"VPS ID `{vps_id}` does not exist."))
        return
    try:
        if vps.get('backend', 'lxc') == 'kvm':
            raw = await execute_lxc(vps['container_name'], f"info {shlex.quote(vps['container_name'])}", node_id=int(vps.get('node_id', 1)), timeout=30)
            lines = [x for x in str(raw or '').splitlines() if any(k in x.lower() for k in ('state:', 'cpu', 'memory', 'autostart'))]
        else:
            raw = await execute_lxc(vps['container_name'], f"config show {shlex.quote(vps['container_name'])}", node_id=int(vps.get('node_id', 1)), timeout=30)
            lines = []
        for line in str(raw or '').splitlines():
            low = line.lower()
            if any(key in low for key in ('security.', 'limits.', 'raw.lxc', 'linux.kernel_modules')):
                lines.append(line)
        text_out = '\n'.join(lines) or 'No matching security/resource keys were returned.'
        embed = create_info_embed("🛡️ VPS Security", f"`{vps['container_name']}`\n\n```yaml\n{text_out[:3500]}\n```")
        await ctx.send(embed=embed)
    except Exception as exc:
        await ctx.send(embed=create_error_embed("Security Check Failed", str(exc)[:1500]))


@bot.command(name='vps-metrics')
async def vps_metrics_cmd(ctx, vps_id: int):
    """Show a deeper guest-side performance/network snapshot."""
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", "Invalid VPS ID.")); return
    uid = str(ctx.author.id)
    if not is_admin_user_id(uid) and str(vps.get('user_id')) != uid and uid not in [str(x) for x in vps.get('shared_with', [])]:
        await ctx.send(embed=create_error_embed("Access Denied", "You do not have access to this VPS.")); return
    name=vps['container_name']; node_id=int(vps.get('node_id',1)); backend=str(vps.get('backend','lxc')).lower()
    script=r'''set +e
printf 'LOAD='; awk '{print $1" "$2" "$3}' /proc/loadavg 2>/dev/null || true
printf 'MEM='; free -m 2>/dev/null | awk '/^Mem:/{print $3"/"$2"MB"}' || true
printf 'DISK='; df -P / 2>/dev/null | awk 'NR==2{print $3"/"$2"KB ("$5")"}' || true
printf 'UPTIME='; uptime -p 2>/dev/null || uptime 2>/dev/null || true
printf 'IP='; ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | paste -sd ',' - || true
printf 'ROUTE='; ip -4 route show default 2>/dev/null | head -n1 || true
printf 'DNS='; getent hosts cloudflare.com >/dev/null 2>&1 && echo OK || echo FAIL
printf 'HTTPS='; curl -4 -fsS --max-time 8 https://www.cloudflare.com/cdn-cgi/trace >/dev/null 2>&1 && echo OK || echo FAIL
printf 'SSH='; (systemctl is-active ssh 2>/dev/null || systemctl is-active sshd 2>/dev/null || true) | head -n1
'''
    try:
        raw=await (kvm_guest_exec(name,script,timeout=30) if backend=='kvm' else _guest_exec_lxc(name,node_id,script,timeout=30))
        embed=create_info_embed("📈 VPS Live Metrics",f"**VPS:** `{name}`\n**Backend:** `{backend.upper()}`\n\n```text\n{str(raw or 'No metrics returned.')[:3500]}\n```")
        await ctx.send(embed=embed)
    except Exception as exc:
        await ctx.send(embed=create_error_embed("Metrics Failed",str(exc)[:1500]))

@bot.command(name='vps-rotate-password')
async def vps_rotate_password_cmd(ctx, vps_id: int):
    """Rotate root password and deliver the new credential privately."""
    vps=get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found","Invalid VPS ID.")); return
    uid=str(ctx.author.id)
    if not is_admin_user_id(uid) and str(vps.get('user_id')) != uid:
        await ctx.send(embed=create_error_embed("Access Denied","Only the VPS owner or an admin can rotate its password.")); return
    if vps.get('suspended') or str(vps.get('status','stopped')).lower()!='running':
        await ctx.send(embed=create_error_embed("VPS Not Ready","The VPS must be running and not suspended.")); return
    new_password=generate_strong_password(24); name=vps['container_name']; node_id=int(vps.get('node_id',1)); backend=str(vps.get('backend','lxc')).lower()
    try:
        if backend=='kvm':
            await kvm_guest_exec(name,f"printf '%s\\n' {shlex.quote('root:'+new_password)} | chpasswd",timeout=30)
        else:
            ok,detail=await configure_ssh(name,node_id,new_password)
            if not ok: raise RuntimeError(str(detail))
        vps['root_password']=new_password; save_vps_data_immediate()
        dm=create_success_embed("🔐 VPS Password Rotated",f"A new root password was generated for `{name}`.")
        add_field(dm,"Username",'`root`',True); add_field(dm,"New Password",f'`{new_password}`',False); add_field(dm,"Security","The old password is no longer valid. Store this credential securely.",False)
        try:
            owner=await bot.fetch_user(int(vps['user_id'])); await owner.send(embed=dm)
            await ctx.send(embed=create_success_embed("🔐 Password Rotated","The new VPS credential was sent to the VPS owner's DM."))
        except discord.Forbidden:
            await ctx.send(embed=create_error_embed("DM Blocked","The password was changed, but Discord DMs are disabled."))
    except Exception as exc:
        await ctx.send(embed=create_error_embed("Password Rotation Failed",str(exc)[:1500]))

@bot.command(name='node-health')
@is_admin()
async def node_health_cmd(ctx, node_id: int = 1):
    """Run a bounded infrastructure health check for one node."""
    node=get_node(node_id)
    if not node:
        await ctx.send(embed=create_error_embed("Node Not Found",f"Node `{node_id}` does not exist.")); return
    try:
        checks=[]
        if node.get('is_local'):
            caps=await get_virtualization_capabilities(node_id)
            checks.append(("LXC/Incus",bool(caps.get('lxc')),"ready" if caps.get('lxc') else "unavailable"))
            checks.append(("KVM/libvirt",bool(caps.get('kvm')),"ready" if caps.get('kvm') else str(caps.get('reason','unavailable'))[:500]))
            host_cmd = r'''printf 'UPTIME='; uptime -p 2>/dev/null || uptime; printf 'DISK='; df -P / | awk 'NR==2{print $5}'; printf 'RAM='; free -m | awk '/^Mem:/{print $3"/"$2"MB"}'; printf 'IP='; hostname -I 2>/dev/null | awk '{print $1}' '''
            raw=await _run_local_process(['bash','-lc',host_cmd],timeout=15,check=False)
            details=raw.strip() if raw else 'No host metrics returned.'
        else:
            raw=await http_request('GET',f"{node['url']}/api/ping",params={'api_key':node['api_key']},timeout=10)
            checks.append(("Remote agent",raw.status_code==200,f"HTTP {raw.status_code}")); details='Remote node ping endpoint checked.'
        lines=[f"{'✅' if ok else '⚠️'} **{label}:** {detail}" for label,ok,detail in checks]
        if node.get('is_local'): lines.append(f"\n**Host metrics**\n```text\n{details[:2200]}\n```")
        await ctx.send(embed=create_info_embed("🩺 Node Health",f"**Node:** `{node['name']}` (ID `{node_id}`)\n\n"+'\n'.join(lines)))
    except Exception as exc:
        await ctx.send(embed=create_error_embed("Node Health Failed",str(exc)[:1500]))


@bot.command(name='snapshot-create')
async def snapshot_create_cmd(ctx, vps_id: int, snapshot_name: str = None):
    """Create a snapshot of the caller's VPS; admins may snapshot any VPS."""
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", "Invalid VPS ID."))
        return
    uid = str(ctx.author.id)
    if not is_admin_user_id(uid) and str(vps['user_id']) != uid:
        await ctx.send(embed=create_error_embed("Access Denied", "You can only snapshot your own VPS."))
        return
    snap = snapshot_name or f"manual-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if not re.match(r'^[A-Za-z0-9._-]{1,64}$', snap):
        await ctx.send(embed=create_error_embed("Invalid Snapshot Name", "Use only letters, numbers, `.`, `_` and `-` (max 64 chars)."))
        return
    try:
        await execute_lxc(vps['container_name'], f"snapshot {shlex.quote(vps['container_name'])} {shlex.quote(snap)}", node_id=int(vps.get('node_id', 1)), timeout=180)
        await ctx.send(embed=create_success_embed("📸 Snapshot Created", f"VPS `{vps['container_name']}`\nSnapshot: `{snap}`"))
    except Exception as exc:
        await ctx.send(embed=create_error_embed("Snapshot Failed", str(exc)[:1500]))


@bot.command(name='snapshot-list')
async def snapshot_list_cmd(ctx, vps_id: int):
    """List snapshots for the caller's VPS."""
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", "Invalid VPS ID."))
        return
    uid = str(ctx.author.id)
    if not is_admin_user_id(uid) and str(vps['user_id']) != uid:
        await ctx.send(embed=create_error_embed("Access Denied", "You can only view snapshots of your own VPS."))
        return
    try:
        raw = await execute_lxc(vps['container_name'], f"snapshot list {shlex.quote(vps['container_name'])}", node_id=int(vps.get('node_id', 1)), timeout=60)
        await ctx.send(embed=create_info_embed("📸 VPS Snapshots", f"`{vps['container_name']}`\n\n```\n{str(raw or 'No snapshots')[:3800]}\n```"))
    except Exception as exc:
        await ctx.send(embed=create_error_embed("Snapshot List Failed", str(exc)[:1500]))


@bot.command(name='snapshot-delete')
async def snapshot_delete_cmd(ctx, vps_id: int, snapshot_name: str):
    """Delete one snapshot from the caller's VPS."""
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", "Invalid VPS ID."))
        return
    uid = str(ctx.author.id)
    if not is_admin_user_id(uid) and str(vps['user_id']) != uid:
        await ctx.send(embed=create_error_embed("Access Denied", "You can only delete snapshots of your own VPS."))
        return
    if not re.match(r'^[A-Za-z0-9._-]{1,64}$', snapshot_name):
        await ctx.send(embed=create_error_embed("Invalid Snapshot Name", "Invalid snapshot name."))
        return
    try:
        await execute_lxc(vps['container_name'], f"snapshot delete {shlex.quote(vps['container_name'])}/{shlex.quote(snapshot_name)}", node_id=int(vps.get('node_id', 1)), timeout=120)
        await ctx.send(embed=create_success_embed("🗑️ Snapshot Deleted", f"Snapshot `{snapshot_name}` deleted."))
    except Exception as exc:
        await ctx.send(embed=create_error_embed("Snapshot Delete Failed", str(exc)[:1500]))


@bot.command(name='node-capabilities')
@is_admin()
async def node_capabilities_cmd(ctx, node_id: int = 1):
    """Show real virtualization capabilities of a node."""
    caps = await get_virtualization_capabilities(node_id)
    node = get_node(node_id)
    details = caps.get('kvm_details', {})
    embed = create_info_embed("🧩 Node Virtualization", f"**Node:** `{node['name'] if node else node_id}`\n**LXC/Incus:** `{'READY' if caps.get('lxc') else 'UNAVAILABLE'}`\n**KVM/libvirt:** `{'READY' if caps.get('kvm') else 'UNAVAILABLE'}`")
    if details:
        add_field(embed, "KVM Checks", f"virsh `{bool(details.get('virsh'))}`\nvirt-install `{bool(details.get('virt_install'))}`\nqemu-img `{bool(details.get('qemu_img'))}`\n/dev/kvm `{details.get('kvm_device')}`", True)
    if caps.get('reason'):
        add_field(embed, "Reason", str(caps['reason']), False)
    add_field(embed, "KVM OS Images", ', '.join(KVM_SUPPORTED_IMAGES.keys()), False)
    await ctx.send(embed=embed)


@bot.command(name='vps-virtualization')
async def vps_virtualization_cmd(ctx, vps_id: int):
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"VPS `{vps_id}` does not exist."))
        return
    uid = str(ctx.author.id)
    if not is_admin_user_id(uid) and str(vps.get('user_id')) != uid and uid not in [str(x) for x in vps.get('shared_with', [])]:
        await ctx.send(embed=create_error_embed("Access Denied", "You do not have access to this VPS."))
        return
    backend = vps.get('backend', 'lxc').upper()
    if backend == 'LXC':
        note = "LXC shares the host kernel by design. `/proc/cpuinfo` and `uname -r` can expose host-level information. This cannot be fully virtualized inside an LXC container."
        fix = "For a separate guest kernel/CPU virtualization, deploy this workload as **KVM** instead."
    else:
        note = "KVM provides a separate guest kernel and virtual machine boundary. The guest CPU model depends on the configured libvirt CPU mode."
        fix = f"CPU mode: `{vps.get('cpu_model') or KVM_CPU_MODE}`"
    embed = create_info_embed("🛡️ Virtualization Details", f"**VPS:** `{vps['container_name']}`\n**Backend:** `{backend}`\n\n{note}\n\n{fix}")
    await ctx.send(embed=embed)


async def kvm_guest_exec(vm_name: str, command: str, timeout: int = 45) -> str:
    """Execute a read-only command inside a KVM guest through QEMU Guest Agent."""
    if not shutil.which('virsh'):
        raise RuntimeError('virsh is not installed on the host.')
    # QEMU Guest Agent does not guarantee a normal login environment. In
    # particular HOME may be unset, which breaks installers that use `set -u`.
    # Always provide a deterministic root environment for guest commands.
    guest_env = (
        'export HOME=\"${HOME:-/root}\"; '
        'export USER=\"${USER:-root}\"; '
        'export LOGNAME=\"${LOGNAME:-root}\"; '
        'export SHELL=\"${SHELL:-/bin/bash}\"; '
        'export PATH=\"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}\"; '
    )
    payload = {
        'execute': 'guest-exec',
        'arguments': {
            'path': '/bin/bash',
            'arg': ['-lc', guest_env + command],
            'capture-output': True,
        },
    }
    raw = await _run_local_process(
        ['virsh', '-c', 'qemu:///system', 'qemu-agent-command', vm_name, json.dumps(payload, separators=(',', ':'))],
        timeout=15,
        check=True,
    )
    try:
        result = json.loads(raw)
        pid = int(result['return']['pid'])
    except Exception as exc:
        raise RuntimeError(f'QEMU Guest Agent did not accept the command: {str(raw)[:800]}') from exc
    deadline = time.monotonic() + max(5, timeout)
    while time.monotonic() < deadline:
        await asyncio.sleep(1)
        status_payload = {'execute': 'guest-exec-status', 'arguments': {'pid': pid}}
        status_raw = await _run_local_process(
            ['virsh', '-c', 'qemu:///system', 'qemu-agent-command', vm_name, json.dumps(status_payload, separators=(',', ':'))],
            timeout=10,
            check=True,
        )
        try:
            status = json.loads(status_raw).get('return', {})
        except Exception:
            continue
        if not status.get('exited'):
            continue
        output = ''
        error = ''
        try:
            if status.get('out-data'):
                output = base64.b64decode(status['out-data']).decode('utf-8', 'replace')
        except Exception:
            output = str(status.get('out-data', ''))
        try:
            if status.get('err-data'):
                error = base64.b64decode(status['err-data']).decode('utf-8', 'replace')
        except Exception:
            error = str(status.get('err-data', ''))
        if status.get('exitcode', 0) not in (0, None) and error:
            raise RuntimeError(error.strip()[:1500])
        return (output + (f'\n[stderr]\n{error}' if error else '')).strip()
    raise RuntimeError('QEMU Guest Agent command timed out.')


async def ensure_kvm_guest_agent_channel(vm_name: str) -> bool:
    """Ensure the standard libvirt/QEMU guest-agent virtio channel exists."""
    xml = await _run_local_process(['virsh', '-c', 'qemu:///system', 'dumpxml', vm_name], timeout=20, check=False)
    if 'org.qemu.guest_agent.0' not in xml:
        device_xml = """<channel type='unix'>
  <target type='virtio' name='org.qemu.guest_agent.0'/>
</channel>"""
        path = f'/tmp/{vm_name}-qga-channel.xml'
        Path(path).write_text(device_xml, encoding='utf-8')
        try:
            await _run_local_process(['virsh', '-c', 'qemu:///system', 'attach-device', vm_name, path, '--live', '--config'], timeout=30, check=False)
        finally:
            try: os.remove(path)
            except OSError: pass
    try:
        await _run_local_process(['virsh', '-c', 'qemu:///system', 'qemu-agent-command', vm_name, '{"execute":"guest-ping"}'], timeout=8, check=True)
        return True
    except Exception:
        return False


async def wait_for_kvm_guest_agent(vm_name: str, timeout: Optional[int] = None, interval: float = 4.0) -> bool:
    """Wait for QEMU Guest Agent without making QGA a hard VPS-creation dependency."""
    total = int(timeout or KVM_QGA_WAIT_TIMEOUT)
    deadline = time.monotonic() + max(15, total)
    last_error = ''
    while time.monotonic() < deadline:
        try:
            if await ensure_kvm_guest_agent_channel(vm_name):
                return True
        except Exception as exc:
            last_error = str(exc)
        await asyncio.sleep(interval)
    if last_error:
        logger.warning('QGA not ready for %s after %ss: %s', vm_name, total, last_error[-500:])
    else:
        logger.warning('QGA not ready for %s after %ss', vm_name, total)
    return False


async def kvm_guest_network_doctor(vm_name: str, repair: bool = False) -> Dict[str, Any]:
    """Inspect/repair guest IPv4 and outbound internet through QEMU Guest Agent."""
    result: Dict[str, Any] = {'ok': False, 'raw': ''}
    qga_ready = await ensure_kvm_guest_agent_channel(vm_name)
    if not qga_ready:
        # Do not report a false 'no IPv4' error just because QGA is offline.
        # The libvirt DHCP lease is host-side and can be checked without QGA.
        leases = await get_kvm_networks(vm_name)
        if leases:
            result['ipv4'] = leases
            result['lease_ready'] = True
            result['qga_ready'] = False
            # A lease proves addressing only, not internet connectivity. Keep
            # this as a recoverable partial state instead of reporting a false
            # full network success to the self-healing agent.
            result['ok'] = False
            result['raw'] = 'IPv4 DHCP lease is present (' + ', '.join(leases.values()) + '), but guest internet cannot be verified because QEMU Guest Agent is offline. VM preserved.'
            result['error'] = 'guest_agent_offline_with_lease'
            return result
        result['qga_ready'] = False
        if repair:
            rescued = await kvm_network_rescue(vm_name, timeout=45)
            if rescued:
                result['ipv4'] = rescued
                result['lease_ready'] = True
                result['ok'] = True
                result['raw'] = 'Recovered the guest NIC using a host-side KVM network restart; QEMU Guest Agent is still offline: ' + ', '.join(rescued.values())
                return result
        result['error'] = 'No IPv4 DHCP lease was detected from libvirt/ARP. QEMU Guest Agent is offline, so guest-side repair is unavailable. The VM was kept running. Check host NAT/DHCP and whether the outer provider permits nested KVM networking.'
        return result
    script = r'''set +e
printf 'OS='; . /etc/os-release 2>/dev/null && printf '%s\n' "${PRETTY_NAME:-Unknown}" || echo Unknown
printf 'IFACE='; ip -o link show | awk -F': ' '$2 != "lo" {print $2; exit}'
printf 'ADDR4='; ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | paste -sd ',' -
printf 'ROUTE4='; ip -4 route show default 2>/dev/null | head -n1
printf 'DNS='; getent hosts cloudflare.com >/dev/null 2>&1 && echo OK || echo FAIL
printf 'PING_GW='; GW=$(ip -4 route show default 2>/dev/null | awk 'NR==1{print $3}'); [ -n "$GW" ] && ping -c1 -W2 "$GW" >/dev/null 2>&1 && echo OK || echo FAIL
printf 'PING_IP='; ping -c1 -W3 1.1.1.1 >/dev/null 2>&1 && echo OK || echo FAIL
printf 'HTTPS='; curl -4 -fsS --max-time 8 https://www.cloudflare.com/cdn-cgi/trace >/dev/null 2>&1 && echo OK || echo FAIL
printf 'SSH='; (systemctl is-active ssh 2>/dev/null || systemctl is-active sshd 2>/dev/null || true) | head -n1
'''
    if repair:
        script = r'''set +e
IF=$(ip -o link show | awk -F': ' '$2 != "lo" {print $2; exit}')
[ -n "$IF" ] && ip link set "$IF" up >/dev/null 2>&1 || true
if command -v nmcli >/dev/null 2>&1; then nmcli device connect "$IF" >/dev/null 2>&1 || true; fi
if command -v dhclient >/dev/null 2>&1; then dhclient -r "$IF" >/dev/null 2>&1 || true; dhclient -1 "$IF" >/dev/null 2>&1 || true; fi
if command -v udhcpc >/dev/null 2>&1; then udhcpc -n -q -i "$IF" >/dev/null 2>&1 || true; fi
if command -v resolvectl >/dev/null 2>&1; then resolvectl dns "$IF" 1.1.1.1 8.8.8.8 >/dev/null 2>&1 || true; resolvectl flush-caches >/dev/null 2>&1 || true; fi
if command -v systemctl >/dev/null 2>&1; then systemctl restart NetworkManager 2>/dev/null || true; systemctl restart systemd-networkd 2>/dev/null || true; systemctl restart networking 2>/dev/null || true; fi
[ -x /usr/local/sbin/voxelcloud-network-heal.sh ] && /usr/local/sbin/voxelcloud-network-heal.sh >/dev/null 2>&1 || true
''' + script
    try:
        raw = await kvm_guest_exec(vm_name, script, timeout=35 if repair else 20)
        result['raw'] = raw
        for line in raw.splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                result[k.lower()] = v.strip()
        result['ok'] = result.get('https') == 'OK' or result.get('ping_ip') == 'OK'
    except Exception as exc:
        result['error'] = str(exc)
    return result

async def configure_kvm_guest_ssh(vm_name: str, password: Optional[str] = None) -> Dict[str, Any]:
    """Install/repair/verify OpenSSH inside a KVM guest through QGA."""
    password = password or get_vps_password(vm_name) or generate_strong_password(20)
    script = r'''
set +e
export HOME="${HOME:-/root}"
export USER="${USER:-root}"
export LOGNAME="${LOGNAME:-root}"
export SHELL="${SHELL:-/bin/bash}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"
export DEBIAN_FRONTEND=noninteractive
mkdir -p /run/sshd /var/run/sshd /etc/ssh/sshd_config.d
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq -y >/dev/null 2>&1 || true
  apt-get install -y openssh-server openssh-client ca-certificates >/dev/null 2>&1 || true
elif command -v apk >/dev/null 2>&1; then
  apk add --no-cache openssh openssh-client ca-certificates >/dev/null 2>&1 || true
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y openssh-server openssh-clients ca-certificates >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then
  yum install -y openssh-server openssh-clients ca-certificates >/dev/null 2>&1 || true
elif command -v zypper >/dev/null 2>&1; then
  zypper --non-interactive install openssh-server openssh-clients ca-certificates >/dev/null 2>&1 || true
fi
if [ -f /etc/ssh/sshd_config ]; then
  cp -n /etc/ssh/sshd_config /etc/ssh/sshd_config.voxelcloud-backup 2>/dev/null || true
  sed -i -E \
    -e 's/^[[:space:]]*#?[[:space:]]*PasswordAuthentication[[:space:]].*$/PasswordAuthentication yes/' \
    -e 's/^[[:space:]]*#?[[:space:]]*KbdInteractiveAuthentication[[:space:]].*$/KbdInteractiveAuthentication no/' \
    -e 's/^[[:space:]]*#?[[:space:]]*PubkeyAuthentication[[:space:]].*$/PubkeyAuthentication yes/' \
    -e 's/^[[:space:]]*#?[[:space:]]*PermitRootLogin[[:space:]].*$/PermitRootLogin yes/' \
    -e 's/^[[:space:]]*#?[[:space:]]*UsePAM[[:space:]].*$/UsePAM yes/' \
    -e 's/^[[:space:]]*#?[[:space:]]*AuthenticationMethods[[:space:]].*$/# AuthenticationMethods disabled by AxionHost/' \
    /etc/ssh/sshd_config
fi
cat > /etc/ssh/sshd_config.d/00-voxelcloud-access.conf <<'SSHEOF'
# AxionHost KVM SSH baseline
Port 22
AddressFamily any
ListenAddress 0.0.0.0
ListenAddress ::
PasswordAuthentication yes
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin yes
PermitEmptyPasswords no
UsePAM yes
MaxAuthTries 6
MaxSessions 10
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
TCPKeepAlive yes
PrintMotd no
PrintLastLog yes
SSHEOF
if ! grep -Eq '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config 2>/dev/null; then
  printf '\nInclude /etc/ssh/sshd_config.d/*.conf\n' >> /etc/ssh/sshd_config
fi
mkdir -p /etc/profile.d
cat > /etc/profile.d/voxelcloud-env.sh <<'ENVEOF'
export HOME="${HOME:-/root}"
export USER="${USER:-root}"
export LOGNAME="${LOGNAME:-root}"
export SHELL="${SHELL:-/bin/bash}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"
ENVEOF
chmod 0644 /etc/profile.d/voxelcloud-env.sh
printf '%s\n' 'root:__VPS_PASSWORD__' | chpasswd >/tmp/voxelcloud-chpasswd.err 2>&1
if command -v sshd >/dev/null 2>&1; then sshd -t || { echo 'SSH_CONFIG=INVALID'; cat /tmp/voxelcloud-chpasswd.err; exit 30; }; fi
(systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd >/dev/null 2>&1 || true)
if ! pgrep -x sshd >/dev/null 2>&1 && command -v sshd >/dev/null 2>&1; then
  /usr/sbin/sshd >/dev/null 2>&1 || sshd >/dev/null 2>&1 || true
fi
EFFECTIVE="$(sshd -T -C user=root,addr=127.0.0.1,host=localhost 2>/dev/null || sshd -T 2>/dev/null || true)"
printf '%s\n' "$EFFECTIVE" | grep -E '^(passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|permitrootlogin|usepam|authenticationmethods) ' || true
printf '%s\n' "$EFFECTIVE" | grep -Eq '^passwordauthentication yes$' || { echo 'SSH_PASSWORD_AUTH=NO'; exit 31; }
printf '%s\n' "$EFFECTIVE" | grep -Eq '^permitrootlogin yes$' || { echo 'SSH_ROOT_LOGIN=NO'; exit 32; }
(ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null || true) | grep -Eq '(^|[[:space:]])[^ ]*:22[[:space:]]' || { echo 'SSH_PORT_22=NOT_LISTENING'; exit 33; }
echo 'SSH_PASSWORD_AUTH=YES'
echo 'SSH_ROOT_LOGIN=YES'
echo 'SSH_PORT_22=LISTENING'
'''.replace('__VPS_PASSWORD__', shlex.quote(password))
    try:
        raw = await kvm_guest_exec(vm_name, script, timeout=120)
        set_vps_password(vm_name, password)
        return {'ok': True, 'raw': raw}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}

async def kvm_guest_pinggy_tunnel(vm_name: str, timeout: int = 35) -> tuple:
    """Create/reuse a public TCP SSH endpoint for a KVM guest through Pinggy."""
    async with _get_tunnel_lock(f"kvm-pinggy:{vm_name}"):
        return await _kvm_guest_pinggy_tunnel_locked(vm_name, timeout)

async def _kvm_guest_pinggy_tunnel_locked(vm_name: str, timeout: int = 45) -> tuple:
    # Create/reuse a public TCP SSH endpoint for a KVM guest through Pinggy.
    if not KVM_PINGGY_ENABLED:
        raise RuntimeError('KVM Pinggy SSH access is disabled by KVM_PINGGY_ENABLED=false.')
    ssh_state = await configure_kvm_guest_ssh(vm_name, get_vps_password(vm_name))
    if not ssh_state.get('ok'):
        raise RuntimeError('KVM SSH authentication repair failed: ' + str(ssh_state.get('error') or ssh_state.get('raw') or 'unknown error')[-1800:])
    try:
        existing = await kvm_guest_exec(
            vm_name,
            'if [ -f /tmp/pinggy-kvm.pid ] && kill -0 "$(cat /tmp/pinggy-kvm.pid)" 2>/dev/null; then cat /tmp/pinggy-kvm.log 2>/dev/null; fi',
            timeout=8,
        )
        m = re.search(r'tcp://([^\s:]+):(\d+)', existing or '')
        if m:
            return m.group(1), m.group(2)
    except Exception:
        pass

    install = r'''set +e
export HOME="${HOME:-/root}"
export USER="${USER:-root}"
export LOGNAME="${LOGNAME:-root}"
export SHELL="${SHELL:-/bin/bash}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"
export DEBIAN_FRONTEND=noninteractive
mkdir -p /run/sshd /var/run/sshd
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y >/dev/null 2>&1 || true
  apt-get install -y openssh-client openssh-server ca-certificates bash coreutils >/dev/null 2>&1 || true
elif command -v apk >/dev/null 2>&1; then
  apk add --no-cache openssh-client openssh-server ca-certificates bash coreutils >/dev/null 2>&1 || true
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y openssh-clients openssh-server ca-certificates bash coreutils >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then
  yum install -y openssh-clients openssh-server ca-certificates bash coreutils >/dev/null 2>&1 || true
elif command -v zypper >/dev/null 2>&1; then
  zypper --non-interactive install openssh-clients openssh-server ca-certificates bash coreutils >/dev/null 2>&1 || true
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd >/dev/null 2>&1 || true
fi
pgrep -x sshd >/dev/null 2>&1 || (command -v sshd >/dev/null 2>&1 && sshd) || true
if ! command -v ssh >/dev/null 2>&1; then echo 'PINGGY_ERROR=ssh_client_missing'; exit 20; fi
rm -f /tmp/pinggy-kvm.log /tmp/pinggy-kvm.pid /tmp/pinggy-kvm.stdin
printf '\n' >/tmp/pinggy-kvm.stdin
{
  echo '=== Pinggy preflight ==='
  echo "HOME=$HOME"
  ssh -V 2>&1 || true
  echo '=== DNS ==='
  getent hosts free.pinggy.io 2>&1 || true
  echo '=== TCP 443 ==='
  if timeout 10 bash -lc 'cat </dev/null >/dev/tcp/free.pinggy.io/443' >/dev/null 2>&1; then echo 'TCP443=OK'; else echo 'TCP443=FAIL'; fi
  echo '=== SSHD 22 ==='
  (ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null || true) | grep -E ':(22)\b' || true
} >/tmp/pinggy-kvm.log 2>&1
if ! grep -q 'TCP443=OK' /tmp/pinggy-kvm.log; then
  echo 'PINGGY_ERROR=tcp_443_unreachable' >>/tmp/pinggy-kvm.log
  exit 22
fi
# Pinggy's documented anonymous TCP reverse-forwarding command. We deliberately
# do not use BatchMode/PreferredAuthentications=none because Pinggy documents
# that some SSH clients may prompt for a password; blank input is accepted.
nohup setsid ssh -4 -p 443 -T \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ConnectTimeout=15 \
  -o ExitOnForwardFailure=yes \
  -R0:127.0.0.1:22 tcp@free.pinggy.io \
  </tmp/pinggy-kvm.stdin >>/tmp/pinggy-kvm.log 2>&1 &
echo $! >/tmp/pinggy-kvm.pid
sleep 1
if ! kill -0 "$(cat /tmp/pinggy-kvm.pid)" 2>/dev/null; then
  echo 'PINGGY_ERROR=ssh_process_exited' >>/tmp/pinggy-kvm.log
fi
'''
    await kvm_guest_exec(vm_name, install, timeout=75)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = await kvm_guest_exec(vm_name, 'cat /tmp/pinggy-kvm.log 2>/dev/null || true', timeout=8)
        m = re.search(r'tcp://([^\s:]+):(\d+)', raw or '')
        if m:
            return m.group(1), m.group(2)
        await asyncio.sleep(1)
    try:
        diag = await kvm_guest_exec(
            vm_name,
            r'''printf '=== Pinggy log ===\n'; tail -n 100 /tmp/pinggy-kvm.log 2>/dev/null || true; printf '\n=== DNS ===\n'; getent hosts free.pinggy.io 2>&1 || true; printf '\n=== SSHD ===\n'; (ss -lntp 2>/dev/null || netstat -lntp 2>/dev/null || true) | grep -E ':(22)\b' || true; printf '\n=== Process ===\n'; if [ -f /tmp/pinggy-kvm.pid ]; then ps -fp "$(cat /tmp/pinggy-kvm.pid)" 2>/dev/null || true; fi; ps -ef 2>/dev/null | grep -E '[s]sh .*free\.pinggy\.io|[p]inggy' || true''',
            timeout=12,
        )
    except Exception:
        diag = ''
    raise RuntimeError(
        'Pinggy SSH tunnel did not publish a TCP endpoint. ' +
        (diag[-4200:] if diag else 'Check guest DNS, outbound TCP 443, and SSH port 22.')
    )


async def kvm_guest_sshx_link(vm_name: str, timeout: int = 25) -> str:
    """Install/start SSHX inside a KVM guest through QEMU Guest Agent."""
    install = r'''set -e
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null 2>&1; then apt-get update -y >/dev/null 2>&1 || true; apt-get install -y curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v apk >/dev/null 2>&1; then apk add --no-cache curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v dnf >/dev/null 2>&1; then dnf install -y curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then yum install -y curl ca-certificates util-linux bash >/dev/null 2>&1 || true
elif command -v zypper >/dev/null 2>&1; then zypper --non-interactive install curl ca-certificates util-linux bash >/dev/null 2>&1 || true
fi
command -v sshx >/dev/null 2>&1 || curl -sSf https://sshx.io/get | sh
SSHX_BIN="$(command -v sshx || printf '%s' /root/.local/bin/sshx)"
if [ -f /tmp/sshx.pid ]; then kill "$(cat /tmp/sshx.pid)" >/dev/null 2>&1 || true; fi
rm -f /tmp/sshx.log /tmp/sshx.pid
if [ -s /tmp/sshx.pid ]; then kill "$(cat /tmp/sshx.pid)" >/dev/null 2>&1 || true; fi; rm -f /tmp/sshx.pid
# sshx owns its own PTY/session. Do not wrap it in `script`: doing so with
# stdin=/dev/null can produce a link whose browser terminal accepts no input.
nohup setsid "$SSHX_BIN" </dev/null >/tmp/sshx.log 2>&1 &
echo $! >/tmp/sshx.pid
'''
    await kvm_guest_exec(vm_name, install, timeout=45)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = await kvm_guest_exec(vm_name, r'''grep -ahoE 'https://sshx\.io/s/[A-Za-z0-9#=_-]+' /tmp/sshx.log 2>/dev/null | head -n1''', timeout=8)
            m = re.search(r'https://sshx\.io/s/[A-Za-z0-9#=_-]+', raw or '')
            if m:
                return m.group(0)
        except Exception:
            pass
        await asyncio.sleep(1)
    try:
        diag = await kvm_guest_exec(vm_name, 'tail -n 40 /tmp/sshx.log 2>/dev/null || true', timeout=8)
    except Exception:
        diag = ''
    raise RuntimeError('SSHX did not publish a link. ' + (diag[-1200:] if diag else 'Check guest internet/SSHX logs.'))


@bot.command(name='vps-neofetch', aliases=['neofetch'])
async def vps_neofetch_cmd(ctx, vps_id: int):
    """Show a real guest-side neofetch/fastfetch summary with a safe fallback."""
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", "Invalid VPS ID."))
        return
    uid = str(ctx.author.id)
    if not is_admin_user_id(uid) and str(vps.get('user_id')) != uid and uid not in [str(x) for x in vps.get('shared_with', [])]:
        await ctx.send(embed=create_error_embed("Access Denied", "You do not have access to this VPS."))
        return
    backend = str(vps.get('backend', 'lxc')).lower()
    try:
        summary_script = """set -u
if command -v fastfetch >/dev/null 2>&1; then
  fastfetch --pipe false 2>/dev/null || fastfetch 2>/dev/null || true
elif command -v neofetch >/dev/null 2>&1; then
  neofetch --stdout 2>/dev/null || neofetch 2>/dev/null || true
fi
printf '\\n--- AxionHost VPS Details ---\\n'
printf 'OS: '; . /etc/os-release 2>/dev/null && printf '%s\\n' "${PRETTY_NAME:-Unknown}" || echo Unknown
printf 'Kernel: '; uname -sr 2>/dev/null || echo Unknown
printf 'CPU Vendor: '; awk -F: '/vendor_id/{gsub(/^ +/,"",$2); print $2; exit}' /proc/cpuinfo 2>/dev/null || echo Unknown
printf 'CPU Model: '; awk -F: '/model name/{gsub(/^ +/,"",$2); print $2; exit}' /proc/cpuinfo 2>/dev/null || lscpu 2>/dev/null | awk -F: '/Model name/{gsub(/^ +/,"",$2); print $2; exit}' || echo Unknown
printf 'vCPU Cores: '; nproc 2>/dev/null || echo Unknown
printf 'Memory: '; free -h 2>/dev/null | awk '/^Mem:/{print $3 " used / " $2}' || echo Unknown
printf 'Disk: '; df -h / 2>/dev/null | awk 'NR==2{print $3 " used / " $2 " (" $5 ")"}' || echo Unknown
printf 'Uptime: '; uptime -p 2>/dev/null || uptime 2>/dev/null || echo Unknown
printf 'Virtualization: %s\\n' '__BACKEND__'
""".replace('__BACKEND__', backend.upper())
        if backend == 'lxc':
            raw = await execute_lxc(
                vps['container_name'],
                f"exec {vps['container_name']} -- bash -lc {shlex.quote(summary_script)}",
                node_id=int(vps.get('node_id', 1)),
                timeout=45,
            )
            note = "LXC guest: the kernel is shared with the host by design."
        else:
            raw = await kvm_guest_exec(vps['container_name'], summary_script, timeout=45)
            note = "KVM guest: information was collected through the QEMU Guest Agent."
        if not raw.strip():
            raise RuntimeError('Guest returned no system information. Make sure the VPS is running.')
        output = raw.strip()[:3800]
        cpu_model = vps.get('cpu_model') or ('host-shared' if backend == 'lxc' else 'libvirt-default')
        embed = create_info_embed(
            "🖥️ VPS Neofetch",
            f"**VPS:** `{vps['container_name']}`\\n**Allocated CPU:** `{vps.get('cpu', 'N/A')} vCPU`\\n**Selected CPU model:** `{processor_display_name(cpu_model)}`\\n\\n```text\\n{output}\\n```\\n{note}",
        )
        await ctx.send(embed=embed)
    except Exception as exc:
        await ctx.send(embed=create_error_embed("Neofetch Failed", str(exc)[:1500]))


@bot.command(name='vps-health')
async def vps_health_cmd(ctx, vps_id: int):
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", "Invalid VPS ID."))
        return
    uid = str(ctx.author.id)
    if not is_admin_user_id(uid) and str(vps.get('user_id')) != uid and uid not in [str(x) for x in vps.get('shared_with', [])]:
        await ctx.send(embed=create_error_embed("Access Denied", "You do not have access to this VPS."))
        return
    try:
        stats = await get_container_stats(vps['container_name'], int(vps.get('node_id', 1)))
        status = str(stats.get('status', vps.get('status', 'unknown'))).upper()
        embed = create_info_embed("❤️ VPS Health", f"**VPS:** `{vps['container_name']}`\n**Backend:** `{vps.get('backend', 'lxc').upper()}`\n**Status:** `{status}`")
        add_field(embed, "CPU", f"{stats.get('cpu', 'N/A')}%", True)
        add_field(embed, "RAM", f"{stats.get('ram', {}).get('pct', 'N/A')}%", True)
        add_field(embed, "Disk", str(stats.get('disk', 'N/A')), True)
        add_field(embed, "Uptime", str(stats.get('uptime', 'N/A')), True)
        await ctx.send(embed=embed)
    except Exception as exc:
        await ctx.send(embed=create_error_embed("Health Check Failed", str(exc)[:1500]))


@bot.command(name='vps-autostart')
@is_admin()
async def vps_autostart_cmd(ctx, vps_id: int, action: str = 'on'):
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", "Invalid VPS ID."))
        return
    action = action.lower()
    if action not in ('on', 'off'):
        await ctx.send(embed=create_error_embed("Usage", f"Use `{PREFIX}vps-autostart <vps-id> <on|off>`."))
        return
    try:
        if vps.get('backend', 'lxc') == 'kvm':
            await _run_local_process(['virsh', 'autostart', vps['container_name']] if action == 'on' else ['virsh', 'autostart', '--disable', vps['container_name']], timeout=30)
        else:
            await execute_lxc(vps['container_name'], f"config set {vps['container_name']} boot.autostart {'true' if action == 'on' else 'false'}", node_id=int(vps.get('node_id', 1)))
        await ctx.send(embed=create_success_embed("⚡ Autostart Updated", f"VPS `{vps['container_name']}` autostart: **{action.upper()}**"))
    except Exception as exc:
        await ctx.send(embed=create_error_embed("Autostart Failed", str(exc)[:1500]))


@bot.command(name='kvm-list')
@is_admin()
async def kvm_list_cmd(ctx):
    caps = _kvm_local_capabilities()
    if not caps['ready']:
        await ctx.send(embed=create_error_embed("KVM Unavailable", "Local KVM/libvirt prerequisites are not ready."))
        return
    try:
        raw = await _run_local_process(['virsh', 'list', '--all'], timeout=30)
        await ctx.send(embed=create_info_embed("🖥️ KVM Virtual Machines", f"```text\n{raw[:3800]}\n```"))
    except Exception as exc:
        await ctx.send(embed=create_error_embed("KVM List Failed", str(exc)[:1500]))


@bot.command(name='deploy-status')
@is_admin()
async def deploy_status_cmd(ctx):
    """Show deployment policy and current VPS capacity."""
    total, running, suspended, stopped, expired = get_slot_stats_deploy()
    embed = create_info_embed("🚀 Deployment Policy", f"**Deploy command:** Admin only\n**Current VPS:** `{total}`\n**Running:** `{running}`\n**Stopped:** `{stopped}`\n**Suspended:** `{suspended}`\n**Expired:** `{expired}`")
    free_cfg = get_free_deploy_config()
    add_field(embed, "Default Resources", f"RAM `{free_cfg['ram']}GB` • CPU `{free_cfg['cpu']}` • Disk `{free_cfg['disk']}GB`", True)
    add_field(embed, "Security", f"Privileged `{VPS_PRIVILEGED}` • Nesting `{VPS_NESTING}` • SSH hardening `{VPS_HARDEN_SSH}`", True)
    add_field(embed, "Virtualization", f"LXC default • KVM configured `{KVM_ENABLED}` • KVM images `{len(KVM_SUPPORTED_IMAGES)}`", True)
    await ctx.send(embed=embed)




# ============================================================================
# ADDITIVE V9 MANAGER FEATURES — merged into the existing LXC/KVM bot
# These commands intentionally use the existing database and permission helpers.
# ============================================================================

def _manager_load_plans():
    """Load plan catalogue from the existing settings table."""
    raw = get_setting("manager_plans_v1", "")
    if raw:
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except (TypeError, json.JSONDecodeError):
            logger.warning("Plan catalogue setting is invalid; using safe defaults.")
    return {
        "starter": {"ram": 2, "cpu": 1, "disk": 20, "days": 30, "price": "Free / invite"},
        "basic": {"ram": 4, "cpu": 2, "disk": 35, "days": 30, "price": "Configure price"},
        "pro": {"ram": 8, "cpu": 4, "disk": 60, "days": 30, "price": "Configure price"},
    }


def _manager_save_plans(plans):
    set_setting("manager_plans_v1", json.dumps(plans, separators=(",", ":"), sort_keys=True))


def _manager_load_plan_requests():
    raw = get_setting("manager_plan_requests_v1", "[]")
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _manager_save_plan_requests(requests_list):
    set_setting("manager_plan_requests_v1", json.dumps(requests_list[-500:], separators=(",", ":")))


@bot.command(name="plans")
async def manager_plans_command(ctx):
    """Show the configurable VPS plans; this command does not charge or provision."""
    plans = _manager_load_plans()
    embed = create_info_embed("🧾 VPS Plans", "Available plans. Submit a request with `.plan-request <plan>`; approval and provisioning remain an admin action.")
    if not plans:
        add_field(embed, "No plans configured", "An administrator can add one with `.plan-add <name> <ramGB> <cpu> <diskGB> <days> <price>`.", False)
    for name, plan in list(sorted(plans.items()))[:20]:
        add_field(embed, name.title(), f"RAM `{plan.get('ram','?')} GB` • CPU `{plan.get('cpu','?')}` • Disk `{plan.get('disk','?')} GB`\nDuration `{plan.get('days','?')} days` • Price: **{str(plan.get('price','Contact admin'))[:100]}**", True)
    await ctx.send(embed=embed)


@bot.command(name="plan-add")
@is_admin()
async def manager_plan_add_command(ctx, name: str, ram_gb: int, cpu: int, disk_gb: int, days: int, *, price: str):
    """Add/update a plan. Price is descriptive only; no payment integration is implied."""
    name = re.sub(r"[^a-zA-Z0-9_-]", "", name.lower())[:24]
    if not name or not (1 <= ram_gb <= 1024 and 1 <= cpu <= 256 and 1 <= disk_gb <= 10000 and 1 <= days <= 3650):
        await ctx.send(embed=create_error_embed("Invalid Plan", "Use valid positive limits: RAM 1–1024 GB, CPU 1–256, disk 1–10000 GB, duration 1–3650 days."))
        return
    plans = _manager_load_plans()
    plans[name] = {"ram": ram_gb, "cpu": cpu, "disk": disk_gb, "days": days, "price": price[:100]}
    _manager_save_plans(plans)
    await ctx.send(embed=create_success_embed("Plan Saved", f"Plan **{name}** saved: `{ram_gb} GB RAM / {cpu} CPU / {disk_gb} GB disk / {days} days`.\nThis only updates the catalogue; it does not change deploy limits or allocate a VPS."))


@bot.command(name="plan-remove")
@is_admin()
async def manager_plan_remove_command(ctx, name: str):
    name = name.lower().strip()
    plans = _manager_load_plans()
    if name not in plans:
        await ctx.send(embed=create_error_embed("Plan Not Found", f"No plan named `{name}` exists."))
        return
    del plans[name]
    _manager_save_plans(plans)
    await ctx.send(embed=create_success_embed("Plan Removed", f"Removed **{name}** from the catalogue. Existing VPS resources are unchanged."))


@bot.command(name="plan-request")
async def manager_plan_request_command(ctx, name: str):
    """Record a plan request for admin review; never grants a free VPS."""
    name = name.lower().strip()
    plans = _manager_load_plans()
    if name not in plans:
        await ctx.send(embed=create_error_embed("Plan Not Found", f"Use `.plans` to view available plans."))
        return
    requests_list = _manager_load_plan_requests()
    if any(str(item.get("user_id")) == str(ctx.author.id) and item.get("plan") == name and item.get("status") == "pending" for item in requests_list):
        await ctx.send(embed=create_warning_embed("Request Already Pending", f"You already have a pending request for **{name}**."))
        return
    next_id = max([int(item.get("id", 0)) for item in requests_list if str(item.get("id", "")).isdigit()] + [0]) + 1
    requests_list.append({"id": next_id, "user_id": str(ctx.author.id), "user_tag": str(ctx.author), "plan": name, "status": "pending", "created_at": (datetime.utcnow().isoformat() + "Z")})
    _manager_save_plan_requests(requests_list)
    await ctx.send(embed=create_success_embed("Request Submitted", f"Your request **#{next_id}** for plan **{name}** has been sent for admin review. This is not a payment or deployment confirmation."))


@bot.command(name="plan-requests")
@is_admin()
async def manager_plan_requests_command(ctx, status: str = "pending"):
    status = status.lower().strip()
    if status not in {"pending", "approved", "rejected", "closed", "all"}:
        await ctx.send(embed=create_error_embed("Invalid Status", "Use `.plan-requests pending|approved|rejected|closed|all`."))
        return
    items = _manager_load_plan_requests()
    if status != "all":
        items = [item for item in items if item.get("status") == status]
    items = items[-20:]
    lines = [f"`#{item.get('id')}` • <@{item.get('user_id')}> • **{item.get('plan')}** • `{item.get('status')}`" for item in reversed(items)]
    await ctx.send(embed=create_info_embed("📋 Plan Requests", "\n".join(lines)[:3900] if lines else f"No `{status}` plan requests."))


@bot.command(name="plan-close")
@is_admin()
async def manager_plan_close_command(ctx, request_id: int, status: str = "closed"):
    status = status.lower().strip()
    if status not in {"approved", "rejected", "closed"}:
        await ctx.send(embed=create_error_embed("Invalid Status", "Use `.plan-close <request-id> approved|rejected|closed`."))
        return
    items = _manager_load_plan_requests()
    for item in items:
        if int(item.get("id", 0)) == request_id:
            item["status"] = status
            item["reviewed_by"] = str(ctx.author.id)
            item["reviewed_at"] = (datetime.utcnow().isoformat() + "Z")
            _manager_save_plan_requests(items)
            await ctx.send(embed=create_success_embed("Request Updated", f"Request `#{request_id}` marked **{status}**. Approval does not automatically create or resize a VPS."))
            return
    await ctx.send(embed=create_error_embed("Request Not Found", f"Could not find request `#{request_id}`."))


@bot.command(name="node-capacity")
@is_admin()
async def manager_node_capacity_command(ctx, node_id: int = 1):
    """Show the existing node stats before admins allocate additional VPS resources."""
    node = get_node(node_id)
    if not node:
        await ctx.send(embed=create_error_embed("Node Not Found", f"Node `{node_id}` does not exist."))
        return
    try:
        stats = await asyncio.wait_for(get_host_stats(node_id), timeout=15)
        cpu = stats.get("cpu", "Unknown")
        ram = stats.get("ram", "Unknown")
        disk = stats.get("disk", "Unknown")
        embed = create_info_embed("🧠 Node Capacity", f"Node **{node.get('name', 'Node')}** (`{node_id}`)\nMode: `{'local' if node.get('is_local') else 'remote'}`")
        add_field(embed, "CPU", f"`{cpu}`", True)
        add_field(embed, "RAM", f"`{ram}`", True)
        add_field(embed, "Disk", f"`{disk}`", True)
        add_field(embed, "Important", "These are reported host metrics, not a guarantee of free allocatable capacity. Check provider limits and nested-LXD support before deploying.", False)
        await ctx.send(embed=embed)
    except Exception as exc:
        await ctx.send(embed=create_error_embed("Capacity Check Failed", str(exc)[:1200]))


async def _manager_find_owned_vps(ctx, vps_id: int):
    vps = get_vps_by_id(vps_id)
    if not vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"VPS ID `{vps_id}` was not found."))
        return None
    user_id = str(ctx.author.id)
    shared = vps.get("shared_with", [])
    if isinstance(shared, str):
        try:
            shared = json.loads(shared)
        except Exception:
            shared = []
    if not is_admin_user_id(user_id) and str(vps.get("user_id")) != user_id and user_id not in {str(x) for x in (shared or [])}:
        await ctx.send(embed=create_error_embed("Access Denied", "You can only inspect your own VPS or one shared with you."))
        return None
    return vps


@bot.command(name="ssh-status")
async def manager_ssh_status_command(ctx, vps_id: int):
    """Check SSH daemon status without revealing passwords or keys."""
    vps = await _manager_find_owned_vps(ctx, vps_id)
    if not vps:
        return
    name = str(vps.get("container_name", ""))
    node_id = int(vps.get("node_id", 1))
    try:
        outputs = []
        for service in ("ssh", "sshd"):
            try:
                out = await execute_lxc(name, f"exec {name} -- systemctl is-active {service}", timeout=15, node_id=node_id)
                outputs.append(f"{service}: {str(out).strip()[:80]}")
                if "active" in str(out).lower():
                    break
            except Exception as exc:
                outputs.append(f"{service}: unavailable ({type(exc).__name__})")
        await ctx.send(embed=create_info_embed("🔐 SSH Service Status", f"VPS `{name}`\n" + "\n".join(f"• {x}" for x in outputs) + "\n\nThis checks the guest service only; it does not verify public IPv4/firewall reachability."))
    except Exception as exc:
        await ctx.send(embed=create_error_embed("SSH Status Failed", str(exc)[:1000]))


@bot.command(name="docker-status")
async def manager_docker_status_command(ctx, vps_id: int):
    """Check Docker service status in a VPS without changing the guest."""
    vps = await _manager_find_owned_vps(ctx, vps_id)
    if not vps:
        return
    name = str(vps.get("container_name", ""))
    node_id = int(vps.get("node_id", 1))
    try:
        out = await execute_lxc(name, f"exec {name} -- systemctl is-active docker", timeout=15, node_id=node_id)
        await ctx.send(embed=create_info_embed("🐳 Docker Status", f"VPS `{name}`\nService: `{str(out).strip()[:100]}`"))
    except Exception as exc:
        await ctx.send(embed=create_warning_embed("Docker Status", f"Docker may not be installed or the service may be unavailable.\nDetails: `{str(exc)[:700]}`"))


@bot.command(name="feature-info")
async def manager_feature_info_command(ctx):
    await ctx.send(embed=create_info_embed("✨ Manager Add-ons", "Added in this build:\n• Configurable plan catalogue and persisted plan requests\n• Admin node-capacity snapshot\n• Owner/admin SSH and Docker service status checks\n• Existing LXC/KVM command set retained\n\nUse `1plans`, `1plan-request <name>`, `1node-capacity [node-id]`, `1ssh-status <vps-id>`, and `1docker-status <vps-id>`. Plan requests do not charge users or automatically provision a VPS."))



# ===== AXIONHOST MERGED FEATURE LAYER (preserves legacy bot) =====

import socket
import ipaddress
import sys
import io
import zlib
import hashlib
import gc
import atexit

# New configuration helpers must exist before their settings are evaluated.

def _clean_env_value(value: Optional[str]) -> str:
    if value is None:
        return ''
    text = str(value).replace('\ufeff', '').replace('\u200b', '').strip()
    if text.lower().startswith('bot '):
        text = text[4:].strip()
    if len(text) >= 2 and text[0] == text[-1] and (text[0] in {'"', "'"}):
        text = text[1:-1].strip()
    return text
def env_float(name: str, default: float=0.0) -> float:
    raw = os.getenv(name, '')
    try:
        value = float(str(raw).strip())
        if value != value or value in (float('inf'), float('-inf')):
            raise ValueError('non-finite numeric value')
        return value
    except (TypeError, ValueError, OverflowError):
        return float(default)
def env_int(name: str, default: int=0) -> int:
    raw = os.getenv(name, '')
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return int(default)

# New configuration/settings not present in the legacy bot.

BASE_DIR = Path(__file__).resolve().parent
BOT_PROCESS_STARTED_AT = datetime.now()
BOT_PROCESS_STARTED_MONOTONIC = time.monotonic()
ENV_FILE = BASE_DIR / '.env'
ENV_TEMPLATE_FILE = ENV_FILE
CONFIG_ADMIN_IDS = tuple(sorted({x.strip() for x in os.getenv('ADMIN_USER_IDS', '').split(',') if x.strip().isdigit()}))
DEFAULT_MOTD_TEXT = os.getenv('HOST_MOTD', 'Welcome to AxionHost Powerfull\nAuthorized access only. VPS resources are monitored for stability and safety.').replace('\\n', '\n')[:1200]
AUTO_MOTD_INSTALLER = str(os.getenv('AUTO_MOTD_INSTALLER', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
VPS_BANDWIDTH_GB = 50
LOG_HEALTH_INTERVAL = max(300, env_int('LOG_HEALTH_INTERVAL', '900'))
HOST_STATS_CACHE_TTL = max(3.0, env_float('HOST_STATS_CACHE_TTL', '8'))
GUEST_ACCESS_RETRY_INTERVAL = max(120, env_int('GUEST_ACCESS_RETRY_INTERVAL', '300'))
MAX_BACKGROUND_REPAIR_CONCURRENCY = max(1, min(4, env_int('MAX_BACKGROUND_REPAIR_CONCURRENCY', '2')))
BANDWIDTH_SAMPLE_INTERVAL = max(300, env_int('BANDWIDTH_SAMPLE_INTERVAL', '600'))
BANDWIDTH_QUOTA_BYTES = VPS_BANDWIDTH_GB * 1024 ** 3
AUTOSAVE_INTERVAL = max(30, env_int('AUTOSAVE_INTERVAL', '60'))
AUDIT_NOISY_COMMANDS = {'ping', 'help', 'quickhelp', 'commands', 'stats', 'info', 'uptime'}
LOG_CHANNEL_SNAPSHOT_LINES = max(8, min(30, env_int('LOG_CHANNEL_SNAPSHOT_LINES', '16')))
VPS_HOSTNAME = os.getenv('VPS_HOSTNAME', 'rgnodes-vps')
MAX_VPS_RAM_GB = max(1, min(22, env_int('MAX_VPS_RAM_GB', '22')))
MIN_VPS_RAM_GB = max(1, min(MAX_VPS_RAM_GB, env_int('MIN_VPS_RAM_GB', '1')))
DEFAULT_VPS_RAM_GB = max(MIN_VPS_RAM_GB, min(MAX_VPS_RAM_GB, env_int('DEFAULT_VPS_RAM_GB', '8')))
DEFAULT_VPS_CPU = max(1, min(10, env_int('DEFAULT_VPS_CPU', '2')))
MAX_VPS_CPU = max(1, min(10, env_int('MAX_VPS_CPU', '10')))
DEFAULT_VPS_STORAGE_GB = max(5, min(100, env_int('DEFAULT_VPS_STORAGE_GB', '25')))
DEFAULT_PORT_QUOTA = env_int('DEFAULT_PORT_QUOTA', '10')
PORT_HOST_MIN = env_int('PORT_HOST_MIN', '20000')
PORT_HOST_MAX = env_int('PORT_HOST_MAX', '50000')
VPS_BACKUP_DIR_NAME = os.getenv('VPS_BACKUP_DIR', 'vps_backups')
VPS_RENEWAL_DAYS = env_int('VPS_RENEWAL_DAYS', '60')
RENEWAL_WINDOW_DAYS = env_int('RENEWAL_WINDOW_DAYS', '2')
ANTI_MINING_ENABLED = str(os.getenv('ANTI_MINING_ENABLED', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
AUTO_DETECT_PUBLIC_IP = str(os.getenv('AUTO_DETECT_PUBLIC_IP', 'false')).strip().lower() in {'1', 'true', 'yes', 'on'}
PUBLIC_IPV4 = os.getenv('PUBLIC_IPV4', '').strip()
PUBLIC_IPV6 = os.getenv('PUBLIC_IPV6', '').strip()
DOCKER_STRICT_DEPLOY = str(os.getenv('DOCKER_STRICT_DEPLOY', 'false')).strip().lower() in {'1', 'true', 'yes', 'on'}
VPS_SWAP_ENABLED = str(os.getenv('VPS_SWAP_ENABLED', 'false')).strip().lower() in {'1', 'true', 'yes', 'on'}
HOST_PROVIDER_NAME = os.getenv('HOST_PROVIDER_NAME', 'AxionHost').strip() or 'AxionHost'
REMOTE_NODE_ONLY = str(os.getenv('REMOTE_NODE_ONLY', 'false')).strip().lower() in {'1', 'true', 'yes', 'on'}
DEFAULT_NODE_ID = max(0, env_int('DEFAULT_NODE_ID', '0'))
HOST_VCPU_OVERCOMMIT_RATIO = max(0.75, min(2.0, env_float('HOST_VCPU_OVERCOMMIT_RATIO', '1.5')))
HOST_RAM_RESERVE_GB = max(2.0, env_float('HOST_RAM_RESERVE_GB', '2'))
HOST_DISK_RESERVE_GB = max(2.0, env_float('HOST_DISK_RESERVE_GB', '10'))
HOST_CPU_MAX_DEPLOY_PCT = max(50.0, min(95.0, env_float('HOST_CPU_MAX_DEPLOY_PCT', '85')))
MIN_HOST_RAM_FREE_PCT_DEPLOY = max(5.0, min(50.0, env_float('MIN_HOST_RAM_FREE_PCT_DEPLOY', '18')))
MAX_DEPLOY_RAM_SHARE = max(0.1, min(0.9, env_float('MAX_DEPLOY_RAM_SHARE', '0.80')))
DEPLOY_EXECUTION_TIMEOUT = max(300, env_int('DEPLOY_EXECUTION_TIMEOUT', '1800'))
WEB_TERMINAL_ENABLED = str(os.getenv('WEB_TERMINAL_ENABLED', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
WEB_TERMINAL_PORT = max(1, min(65535, env_int('WEB_TERMINAL_PORT', '909')))
WEB_TERMINAL_PUBLIC_URL = os.getenv('WEB_TERMINAL_PUBLIC_URL', 'https://ssh.rgnodes.bond').strip().rstrip('/') or 'https://ssh.rgnodes.bond'
WEB_TERMINAL_TOKEN = _clean_env_value(os.getenv('WEB_TERMINAL_TOKEN', ''))
WEB_TERMINAL_MAX_SESSIONS = max(1, min(8, env_int('WEB_TERMINAL_MAX_SESSIONS', '3')))
GUEST_BOOTSTRAP_TIMEOUT = max(120, env_int('GUEST_BOOTSTRAP_TIMEOUT', '600'))
AUTO_RESOURCE_ALLOCATION = str(os.getenv('AUTO_RESOURCE_ALLOCATION', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
DOCKER_INSTALL_ON_DEPLOY = str(os.getenv('DOCKER_INSTALL_ON_DEPLOY', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
PINGGY_ENABLED = str(os.getenv('PINGGY_ENABLED', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
PINGGY_AUTO_START = str(os.getenv('PINGGY_AUTO_START', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
PINGGY_HOST = os.getenv('PINGGY_HOST', 'free.pinggy.io').strip() or 'free.pinggy.io'
PINGGY_SSH_PORT = max(1, min(65535, env_int('PINGGY_SSH_PORT', '443')))
PINGGY_REMOTE_PORT = max(0, min(65535, env_int('PINGGY_REMOTE_PORT', '0')))
AUTO_CREATE_SERVER_EMOJIS = str(os.getenv('AUTO_CREATE_SERVER_EMOJIS', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
EMOJI_PROVISION_LOCK = asyncio.Lock()
DEPLOYMENT_GLOBAL_LOCK = asyncio.Lock()
TUNNEL_SETUP_LOCKS: Dict[tuple[str, int], asyncio.Lock] = {}
HOST_STATS_CACHE: Dict[int, tuple[float, Dict[str, Any]]] = {}
HOST_STATS_CACHE_LOCK = asyncio.Lock()
TUNNEL_REPAIR_INTERVAL = max(180, env_int('TUNNEL_REPAIR_INTERVAL', '900'))
ACCESS_REPAIR_INTERVAL = max(180, env_int('ACCESS_REPAIR_INTERVAL', '600'))
TUNNEL_START_TIMEOUT = max(25, env_int('TUNNEL_START_TIMEOUT', '65'))
DEPLOY_NODE_SERIALIZE = str(os.getenv('DEPLOY_NODE_SERIALIZE', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
RESOURCE_AUTOSCALE_ENABLED = str(os.getenv('RESOURCE_AUTOSCALE_ENABLED', 'false')).strip().lower() in {'1', 'true', 'yes', 'on'}
RESOURCE_AUTOSCALE_INTERVAL = max(300, env_int('RESOURCE_AUTOSCALE_INTERVAL', '300'))
RESOURCE_SCALE_UP_RAM_THRESHOLD = max(60.0, min(95.0, env_float('RESOURCE_SCALE_UP_RAM_THRESHOLD', '80')))
RESOURCE_SCALE_UP_CPU_THRESHOLD = max(60.0, min(98.0, env_float('RESOURCE_SCALE_UP_CPU_THRESHOLD', '85')))
RESOURCE_SCALE_UP_DISK_THRESHOLD = max(60.0, min(98.0, env_float('RESOURCE_SCALE_UP_DISK_THRESHOLD', '80')))
RESOURCE_SCALE_UP_DISK_STEP_GB = max(1, env_int('RESOURCE_SCALE_UP_DISK_STEP_GB', '10'))
HOST_PROCESSOR_NAME = os.getenv('HOST_PROCESSOR_NAME', 'AxionHost Powerfull Free').strip() or 'AMD Ryzen'
VPS_ENABLED = str(os.getenv('VPS_ENABLED', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
VPSCTL_PATH = os.getenv('VPSCTL_PATH', '').strip()
VPS_MAX_RAM_GB = max(1, min(22, env_int('VPS_MAX_RAM_GB', str(MAX_VPS_RAM_GB))))
VPS_MAX_CPU = max(1, min(10, env_int('VPS_MAX_CPU', str(MAX_VPS_CPU))))
VPS_MIN_DISK_GB = max(5, env_int('MIN_VPS_DISK_GB', '10'))
VPS_MAX_DISK_GB = max(VPS_MIN_DISK_GB, min(100, env_int('MAX_VPS_DISK_GB', '100')))
INITIAL_VPS_RAM_GB = max(1, min(VPS_MAX_RAM_GB, env_int('INITIAL_VPS_RAM_GB', '8')))
INITIAL_VPS_CPU = max(1, min(VPS_MAX_CPU, env_int('INITIAL_VPS_CPU', '2')))
INITIAL_VPS_DISK_GB = max(VPS_MIN_DISK_GB, min(VPS_MAX_DISK_GB, env_int('INITIAL_VPS_DISK_GB', '25')))
KVM_NETWORK_MODE = os.getenv('KVM_NETWORK_MODE', 'direct').strip().lower()
PUBLIC_BRIDGE_NAME = os.getenv('PUBLIC_BRIDGE_NAME', '').strip()
PUBLIC_PARENT_INTERFACE = os.getenv('PUBLIC_PARENT_INTERFACE', '').strip()
PUBLIC_IPV4_POOL_CIDR = os.getenv('PUBLIC_IPV4_POOL_CIDR', '').strip()
PUBLIC_IPV4_GATEWAY = os.getenv('PUBLIC_IPV4_GATEWAY', '').strip()
REAL_PUBLIC_IPV4_REQUIRED = str(os.getenv('REAL_PUBLIC_IPV4_REQUIRED', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
VPSCTL_CANDIDATES = tuple(dict.fromkeys((x for x in [VPSCTL_PATH, '/usr/local/sbin/vpsctl', '/usr/local/bin/vpsctl'] if x)))
KVM_CONTROLLER_MARKERS = ('LXD/LXC only', 'def compat(', 'lxc')
_EMBEDDED_VPSCTL_ZLIB_B64 = 'eNqlGWtv48bxu37F1imw5HlFPexzGzo81Hd1k0OT3OHuEgQVVGJFrizWfJVLynJc//fOzC4fsuTLBYEBi5ydnZ33Y/nVnyaNriarJJ+ofMvK+3pT5Gejk5OTq11S5N8Vumbf//L3yfe/vGFFnt6zqMjrqkhTVXnsHQIymcsbpVkuMxUjLqHIJFeV9oDOKMnKoqqZrG5KWWkl/qOLXBRaVEroTap2QjersioipbXQ91rUSQYrKqpUDYC6SvIbQGzqJB2tqyJjpaw3abJilu57eB19ePfuU4BPTqG9G1WDLA6/+uXtux+/e/fxU/jz+48honDBJ1tZTWD7RKJ8G5BvvC01d93RD9efrgLEmvBM1ZJfso/Xbz5cf/pogZYlgL++evPPn9638JWMbhsgMVoXFStZkjMHSQm7W1hs12ell93GSeWAHlRe6+BT1Sihdomuw+KW3tzRj1c/XAeV8qIiK5NUORX/90KOf70a/2s6/nrZP4beePkwExfzxz9zdxSrNdvKNImd3PVHLFmzvKgZ0vLWTZpmso42uMQqmWjFfpZpo66rqqgc/janjQx0RDYEagzkbKqc5US3anJHklWKpg7OplMRbVRk+YXDyqA3oGeR1a420uk6xl0DjPdv318jWFXVAbg9xP66JAmdxmQeg/4MY1ERq1aUD02O2EYYp/QMZYam8Mzh+MyNX2YZkllLUGzM3cUYhJn6y17gkgQmi2ijLgNHqRY83UXgQEm+LrjIl+JsKv4hU63cAVdBMCUS6EDGFHV171sq6PheWshYO+QhE6c12Sn3cBG8EGjJOET9OeCSwEqkyrol8MDJQH7+SIdouVVOLjI8Zh08Q/GS1cHau0vqTaib9TrZOdyrs5IWvLsqqZU5jZiLm6zUTiaSPAYHDeYuYEFARZusiJ1aTIuL6ZQ2VqpMZaSctXG9pOyFHTEWy1oGA2mH6ktBt6A+wcdjiBdwTIARp0sxn7rWZCA5w2jKkwjjCektpksMbIfrWtaKi4dH17znqr4rqlsD2aJjawd5MRQk7gcyBlfGcQXOpjQXi6VBQg+TZnUtsyS9524QgJFVzcnnMI7k3m5gmCOjsqo16tXhs/lfPO62VpKLDnPZWbCUWnduxjlp7QZYrcOobIzyyKS5LA33GAZDvamdiqze4C0ivU0weCaoENDerHNHo0OgkYIYQY7WdXakjR1qA9Y8XaZJjcugK9TAbk8eYImBLwpgFC0BStXBIslrZ+f2ZHC3oeO4i5m/XCIdBDIFXLAFyM6SOFUB+qRenC1PzcO5QVQ5vbqvzg3+1CVGEGYBsN/qSzeZQRZIsHMzGRh1gUNCBvB0qlTpeLM5AFb9UlHLNFiB+4zRhy4NT6vFDN9ny/6Qqmjy2MnkzpmKLMmdGSQ6h3aPcYv7AgATegfNzIhZens1tfx609ba7Jp+oL60PoGLvcnjRN/uBcznjR2v4d/49QwtjoZ+uW/oPWO25gL4Yjxbtga6ZI1WcYA2JCPMl51qOtgMYZZfxBa0/hmZhJEJ/U9bF/7DgQ8mGgHFACk9jfdLlgU2sY56eXRt8DKVFdX9IDE0GvoSLqYuFoDpnryZwahkFt6sOFgTrTs/f/HiDGQA44QkPz2ZTXt2GzEIkDDXe8cD6HNn58UdVTUP/6E9ijRuSVhuUmmyAYC5ML+03T6aLRKyOej2cBPqEw6hHfh7CV4pS1QSubQ3nc5wfWyIWBnKCPyu93uv83x4csy5Y8OoO5mpryeW5ASxZ2LAO0kPaqQo6eLDUHgVGBKDMMkWe9IuA/NwubeAWS0Ali/7Qtdl0K4SCvKPRnO/NYR9F/yn/BZ2QwkEZ7xTleMK60tfhJqU23PuU2ETJJ5vFSbQbbj/wNFHuG/Uh88T40JzEF5wcpt2lV72loHO3lajUJNdUIWA9AiBD/7G/TV/MJidZ1pSZ2LuPrJvX7MJG2IMT2tRuCFGu8PVfQ0V0O8dnTcluiX3qU2qTEfFSdAwTbKkxijxD4LGIERNhd3scyioNaLRrVpfMUt29+EicXdwOEGJ9NQ1TRD2yRAOURbbXhRHCpv2EAhhUwYlpBV0yNL4INRffIOFgG+UTOsNxyw8zFZbmF6SNjld7i3puqgourneFHdcHJ04QJHhx0/vPlx9e426V2vZpDV3iVxfcx467+UFdDA0Sqg8NobAmQvz5g4Cdgstq1ylYCLqqpGTQ6BlLMQW8r4F2vYohA4ODQzUxmZii4F22azSJArR18OyKNIQRrd1ctNU6NlUZMDGoKBwiFip/zZJj/HY6zLJ0cxY9zM4IGAl1BRIfYFpSktTdYoSJp+HR9vhrVN5I27VvbAqovHJgRqBQWZCDd0BIeQanYMghOLDhgl6hOnosKbiIQsgu6QEWy5KD1vanYPHuaczbPlZ25r1uJaHETWFwyngcNLgOC7JlFRtUalXspOXM/smILokwfKb4OKcuskOjGIA+GxO4JctmEQB+BwGk6PT2gdQPpQimLShwSyaCmYnmKwVdhA6iRWrNwoYgId+Tof0uVb1PaNgMlzuzzNgNEEWo+qsf69Hfz0ll7atzB5t404YKcrUfsOD19bq9cnDQEuP374+MZb5EhrkCLqunIFC3c9sj9U2idSATlUU2IPo5Fc14MRYoGcFG3cIoDjgMFEVUB3tNQAMRQXQc8wFhSd1lCRhquoaEsepBcbJDXB6yv/0t6+46ZxD9O9K5jfKgURAB9ji9vDiBTIADINPgX2x/PmDjgGC1XLC/fbp8UBa6uLtdEpWeXrq2dSOPYOWee62g5CZ41bAwe3IQJ7vSvUGu9KUXCjmz47D5rTnyaxkT2h9okCrjCzjP3RScvY/Fm3oNT5Ziov2IBL+oB/YK9yHOuuaAA485WClo2kX05NND09VHCuwsuo7WfAp6MnnLVOXJmhtUqR01loFE3SJSU0ZAFmiz47Uf8sIW+zgwe7x9/f6T0n43dPjoiiX+6FtaIEznAKk47XL1kSK0k+3iOyW7fwGXdxfh8UK60mf660ajojwm8o6o0sEewWSD+4+mhymmFsnS7QGw3R3YoBr79IMuonAz244ZLmzRK151zS6e1cz5vbDjDOtRDBDua47LHHrgvvPXgsNt6Gg/TDeEqAx6BgBWjiyxzBeQcZERXJK1Fi6q2KdpGrQj7hH2bLohnovBoGtpQ/6mo6VpzcK7XYah8ZJ2QkC4TbwgYG+INmOrb2OuMpzdh3cS7VdQ3sLdXRHdzN11FUp4Rw5PQnatgBTEbQFuAMfB2EwH1wQPJPDlqflIvFNHTzQlC0/vmkN8NajdF8FL811JrBhVETrDHoQ6FTPoGWiayx4Pl/aNIxLwX719GBm4DjtHVvr2mpcfFJ1j5GE6nmcHi4cJYb1dpCAn6/Yg+aPGj2SjTLm4KZqoJuLoW5s0bag+VN1iVZRL9ubDh5wO3zCE9kR1owpHXwU5eJiOTjuop0I3N8SZr9/aKU6A6nQTl8k2svfEE3G8dHUcMgDYh7wgI740v8D52OS2aovZMEiH3Lx5PyjIRkV5T1ZsUhjkau7YWCKvXFhnwnYJewWE3Dt5YC6E3Q1BIvuc3kAnJiahN97rKm5sOVJnR+gGFV0nJkKZ2+rkKUhm33tg5UvqX5HhcFvX2NymMPEhl+1BOXoAMURJqlAxaiLoJ+FIHcRCDPf0qY+AxjkP15HJYe2JI6rgHqqfsZBmH9sNHrTfv9jG6kBlb19vz1n9k6c3WPCxo8Eagsejx/hxvwUOT7l8EAMjNiXuH8OM+OWCuEORwmqWgpaJyLx6E89+vMfkPYjIgCdXEV1h/GALMEPaQowoIesgxq0bBq6Z1sfUn0bK8e1T3r/Yyr/XUEIlei4Kocue6yvUDuUhhoFenBtpbKFk2D+0QJo9g0DCGVeYtN4JPz3exKzF3cNo+7p3mO+9VOumxK322/NRakqSbfSjJ9GWbzwgcbSfJXKwAnpY4osg/brs3dV3TQZVLP3+FbhTawsPXCEUNoFh9NViTDznQ5gtKQrJr48hmu/KeLnNBnAKh2C63QXb2di8HuYlQN7VSU9u8lFB8H7iUH3aVCpgCWQBqAZzWHINFDhxElUC/RzsSqK1HWNw9g9hzf1DMJP+fYQHJWVK7BpDPS9th9KMTPBi9pB7Zy5Izg2DDFLhiHYPwxRhWHIfaPK0f8BH2xshw=='
_EMBEDDED_VPSCTL_SHA256 = '724a4015f42ed4f813350658dfd7f740eb9e50213113f0a4f804af0b579cfab9'
CUSTOM_EMOJI_NAMES = {'online': os.getenv('EMOJI_ONLINE', 'StatusOnline'), 'status': os.getenv('EMOJI_STATUS', 'StatusOnline'), 'vps': os.getenv('EMOJI_VPS', 'rgnodes_vps'), 'deploy': os.getenv('EMOJI_DEPLOY', 'rgnodes_deploy'), 'rocket': os.getenv('EMOJI_ROCKET', 'rgnodes_rocket'), 'server': os.getenv('EMOJI_SERVER', 'rgnodes_server'), 'cpu': os.getenv('EMOJI_CPU', 'rgnodes_cpu'), 'ram': os.getenv('EMOJI_RAM', 'rgnodes_ram'), 'disk': os.getenv('EMOJI_DISK', 'rgnodes_disk'), 'network': os.getenv('EMOJI_NETWORK', 'rgnodes_network'), 'docker': os.getenv('EMOJI_DOCKER', 'rgnodes_docker'), 'ssh': os.getenv('EMOJI_SSH', 'rgnodes_ssh'), 'ports': os.getenv('EMOJI_PORTS', 'rgnodes_ports'), 'password': os.getenv('EMOJI_PASSWORD', 'rgnodes_password'), 'reinstall': os.getenv('EMOJI_REINSTALL', 'rgnodes_reinstall'), 'renew': os.getenv('EMOJI_RENEW', 'rgnodes_renew'), 'start': os.getenv('EMOJI_START', 'rgnodes_start'), 'stop': os.getenv('EMOJI_STOP', 'rgnodes_stop'), 'stats': os.getenv('EMOJI_STATS', 'rgnodes_stats'), 'refresh': os.getenv('EMOJI_REFRESH', 'rgnodes_refresh'), 'delete': os.getenv('EMOJI_DELETE', 'rgnodes_delete'), 'success': os.getenv('EMOJI_SUCCESS', 'rgnodes_success'), 'warning': os.getenv('EMOJI_WARNING', 'rgnodes_warning'), 'error': os.getenv('EMOJI_ERROR', 'StatusOffline'), 'offline': os.getenv('EMOJI_OFFLINE', 'StatusOffline'), 'loading': os.getenv('EMOJI_LOADING', 'Loading'), 'maintenance': os.getenv('EMOJI_MAINTENANCE', 'WiFi_Maintenance'), 'pinggy': os.getenv('EMOJI_PINGGY', 'WiFi_Online'), 'pinggy_offline': os.getenv('EMOJI_PINGGY_OFFLINE', 'WiFi_Offline')}
PROCESS_LOCK_HANDLE = None
BASE_DIR = Path(__file__).resolve().parent
_data_dir_env = os.getenv('AXIONHOST_DATA_DIR', '').strip()
DATA_DIR = Path(_data_dir_env) if _data_dir_env else Path(os.getenv('AXIONHOST_VPS_ROOT', '/var/lib/rgnodes-vps')) / 'data'
DB_FILE = str(DATA_DIR / 'vps.db')
DB_BACKUP_DIR = DATA_DIR / 'db_backups'
DB_LOCK = threading.RLock()
VPS_BACKUP_DIR = DATA_DIR / VPS_BACKUP_DIR_NAME
DEPLOYMENT_STAGES = ['Receiving VPS ID', 'Checking LXD', 'Creating VPS Container', 'Applying Resource', 'Configure Package', '🐳 Docker Ready', 'Booting VPS', 'Fixing systemctl', 'Register In Bot Database', 'Installing SSH + Password', 'Making Public Real IPv4', 'Creating SSH', 'Creating PINGGY', 'Final Full Check and Repair', 'Finished']
_DEPLOY_SPINNER_FRAMES = ('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')
ANSI_RE = re.compile('\\x1b\\[[0-?]*[ -/]*[@-~]')
PINGGY_ENDPOINT_RE = re.compile(r'(?:tcp://)?([A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9-]{2,}(?:\.[A-Za-z0-9-]{2,})+):(\d{2,5})', re.I)
MAINTENANCE_SAFE_COMMANDS = set()
MAX_VPS_DISK_GB = VPS_MAX_DISK_GB
ACTIVE_DEPLOYMENTS = set()
EXPIRATION_WARNING_SENT = set()
EXPIRATION_EXPIRED_NOTICE_SENT = set()
PORT_OPERATION_LOCK = asyncio.Lock()
TUNNEL_OPERATION_LOCKS = {}
DEPLOY_NODE_LOCKS = {}
AUDIT_CHANNEL_SEND_LOCK = asyncio.Lock()
status_task_handle = None
expiration_task_handle = None
protection_task_handle = None
tunnel_repair_task_handle = None
access_repair_task_handle = None
_WEB_TERMINAL_RUNNER = None
_WEB_TERMINAL_TOKEN_CACHE = None
_WEB_TERMINAL_SESSIONS: Dict[str, float] = {}
_WEB_TERMINAL_LOGIN_ATTEMPTS: Dict[str, List[float]] = {}
_WEB_TERMINAL_ACTIVE_SESSIONS = set()
_WEB_TERMINAL_HTML = '<!doctype html>\n<html lang="en"><head>\n<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">\n<title>AxionHost OpenSSH Terminal</title>\n<style>\n:root{color-scheme:dark;--bg:#101216;--panel:#191d24;--line:#343b46;--text:#e8edf4;--muted:#9aa5b4;--accent:#a8e7b3;--danger:#ffb4a8}\n*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;min-height:100vh;display:flex;flex-direction:column}\nheader{padding:16px clamp(14px,3vw,30px);border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;background:#15181e}.brand{font-weight:750;letter-spacing:.02em}.sub{color:var(--muted);font-size:.84rem}main{width:min(1200px,100%);margin:0 auto;padding:clamp(12px,3vw,24px);flex:1;display:flex;flex-direction:column;gap:14px}\n.card{border:1px solid var(--line);background:var(--panel);border-radius:14px;padding:clamp(13px,2.5vw,22px);box-shadow:0 8px 26px #0002}h1{font-size:1.15rem;margin:0 0 6px}p{margin:5px 0 14px;color:var(--muted)}label{display:flex;flex-direction:column;gap:6px;font-size:.85rem;color:var(--muted);min-width:0}\ninput,button,textarea{font:inherit;border:1px solid var(--line);border-radius:9px;padding:11px 12px;background:#101319;color:var(--text);min-width:0}input:focus,textarea:focus{outline:2px solid #9eb6a3;outline-offset:1px}button{cursor:pointer;font-weight:650;background:#252b34}button:disabled{opacity:.45;cursor:not-allowed}.row{display:grid;grid-template-columns:minmax(0,2fr) minmax(90px,.7fr) minmax(110px,1fr) auto;gap:10px;align-items:end}.login-row{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:end}.hint{font-size:.82rem;color:var(--muted);overflow-wrap:anywhere}.notice{color:var(--danger);min-height:1.3em}.hidden{display:none!important}.terminal{min-height:40vh;max-height:60vh;overflow:auto;background:#07090c;border:1px solid #303843;border-radius:10px;padding:12px;color:#d8f0dc;font:13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}.terminal-input{width:100%;font:13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;border-radius:0 0 10px 10px;border-top:0;background:#07090c;color:#e8f6eb;resize:vertical;min-height:44px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.status{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:.84rem}.safe{border-left:3px solid var(--accent);padding-left:10px}footer{padding:14px;text-align:center;color:var(--muted);font-size:.8rem}\n@media(max-width:760px){.row{grid-template-columns:1fr 1fr}.row label:first-child{grid-column:1/-1}.row button{min-height:44px}.login-row{grid-template-columns:1fr}.terminal{min-height:34vh;max-height:48vh}.card{border-radius:11px}}\n</style></head><body>\n<header><div><div class="brand">AxionHost OpenSSH Terminal</div><div class="sub">Secure browser SSH client · <a href="https://ssh.rgnodes.bond" rel="noopener noreferrer">ssh.rgnodes.bond</a></div></div><div class="sub" id="topStatus">Locked</div></header>\n<main>\n<section class="card" id="loginCard"><h1>Terminal access</h1><p>Enter the private AXIONHOST terminal token stored on the server. The token is never put in the URL.</p><form id="loginForm" class="login-row"><label>Access token<input id="token" type="password" autocomplete="current-password" required minlength="20" placeholder="Paste the local terminal token"></label><button type="submit">Unlock terminal</button></form><div class="notice" id="loginNotice"></div><div class="hint">Keep this page private. SSH credentials are typed directly into the remote SSH session and are not saved by this web page.</div></section>\n<section class="card hidden" id="terminalCard"><h1>Connect to an SSH host</h1><p class="safe">Only use systems you own or are authorized to administer. Host input is validated and passed as an argument to the local OpenSSH client; no shell command is constructed.</p>\n<form id="connectForm" class="row"><label>Host / IP<input id="host" required maxlength="253" autocomplete="url" placeholder="203.0.113.10 or server.example.com"></label><label>SSH port<input id="port" type="number" min="1" max="65535" value="22" required></label><label>Username<input id="username" maxlength="32" value="root" required autocomplete="username"></label><button id="connectButton" type="submit">Connect SSH</button></form>\n<div class="status"><span id="connectionStatus">Not connected</span><span>Private key: host user\'s SSH config · Password prompt supported</span></div><pre class="terminal" id="screen" role="log" aria-live="polite">AxionHost OpenSSH Terminal\nType a host above and press Connect SSH.\n</pre><textarea class="terminal-input" id="keyboard" rows="1" spellcheck="false" autocomplete="off" autocapitalize="off" autocorrect="off" placeholder="Tap here, then type into the remote shell (Enter sends; Ctrl+C interrupts)"></textarea>\n<div class="actions"><button type="button" id="ctrlC">Ctrl+C</button><button type="button" id="ctrlD">Ctrl+D</button><button type="button" id="clear">Clear screen</button><button type="button" id="disconnect">Disconnect</button><button type="button" id="logout">Lock terminal</button></div><div class="notice" id="terminalNotice"></div></section>\n</main><footer>AxionHost · OpenSSH · HTTPS through a loopback-only reverse proxy</footer>\n<script>\nconst $=id=>document.getElementById(id);let ws=null,unlocked=false;\nfunction status(s){$(\'topStatus\').textContent=s;$(\'connectionStatus\').textContent=s}\nfunction output(s){const pre=$(\'screen\');pre.textContent+=s;if(pre.textContent.length>50000)pre.textContent=pre.textContent.slice(-40000);pre.scrollTop=pre.scrollHeight}\nfunction send(v){if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify(v));else $(\'terminalNotice\').textContent=\'Connect to an SSH session first.\'}\n$(\'loginForm\').addEventListener(\'submit\',async e=>{e.preventDefault();$(\'loginNotice\').textContent=\'Checking token…\';try{const r=await fetch(\'/api/login\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({token:$(\'token\').value})});const d=await r.json();if(!r.ok)throw new Error(d.error||\'Access denied\');unlocked=true;$(\'token\').value=\'\';$(\'loginCard\').classList.add(\'hidden\');$(\'terminalCard\').classList.remove(\'hidden\');$(\'loginNotice\').textContent=\'\';status(\'Unlocked · no SSH connection\');$(\'host\').focus()}catch(e){$(\'loginNotice\').textContent=e.message||\'Access denied\';$(\'token\').select()}});\n$(\'connectForm\').addEventListener(\'submit\',e=>{e.preventDefault();if(!unlocked)return;closeSocket();$(\'terminalNotice\').textContent=\'\';$(\'connectButton\').disabled=true;$(\'screen\').textContent=\'Starting OpenSSH…\\n\';let scheme=location.protocol===\'https:\'?\'wss:\':\'ws:\';ws=new WebSocket(scheme+\'//\'+location.host+\'/ws\');ws.binaryType=\'arraybuffer\';ws.onopen=()=>{send({type:\'connect\',host:$(\'host\').value.trim(),port:Number($(\'port\').value),username:$(\'username\').value.trim(),cols:100,rows:28});status(\'Connecting…\')};ws.onmessage=e=>{if(e.data instanceof ArrayBuffer){let t=new TextDecoder().decode(e.data);t=t.replace(/\\x1b\\[[0-?]*[ -/]*[@-~]/g,\'\').replace(/\\x1b\\][^\\x07]*(?:\\x07|\\x1b\\\\)/g,\'\');output(t)}else{try{const m=JSON.parse(e.data);if(m.type===\'status\'){output(\'\\n\'+m.data+\'\\n\');status(m.data);if(m.done)$(\'connectButton\').disabled=false}else if(m.type===\'error\'){$(\'terminalNotice\').textContent=m.data;output(\'\\n[ERROR] \'+m.data+\'\\n\');$(\'connectButton\').disabled=false}}catch{output(e.data)}}};ws.onerror=()=>{$(\'terminalNotice\').textContent=\'WebSocket error. Check the local service and SSH host.\';$(\'connectButton\').disabled=false};ws.onclose=()=>{$(\'connectButton\').disabled=false;if($(\'connectionStatus\').textContent.startsWith(\'Connected\'))status(\'Disconnected\')}});\nfunction closeSocket(){if(ws){try{ws.close()}catch{}ws=null}$(\'connectButton\').disabled=false}\n$(\'keyboard\').addEventListener(\'input\',e=>{const value=e.target.value;if(value){send({type:\'input\',data:value});e.target.value=\'\'}});\n$(\'keyboard\').addEventListener(\'keydown\',e=>{const controls={Enter:\'\\r\',Backspace:\'\\x7f\',Tab:\'\\t\',ArrowUp:\'\\x1b[A\',ArrowDown:\'\\x1b[B\',ArrowRight:\'\\x1b[C\',ArrowLeft:\'\\x1b[D\',Escape:\'\\x1b\'};let data=controls[e.key];if(e.ctrlKey&&e.key.toLowerCase()===\'c\')data=\'\\x03\';else if(e.ctrlKey&&e.key.toLowerCase()===\'d\')data=\'\\x04\';else if(e.ctrlKey&&e.key.toLowerCase()===\'z\')data=\'\\x1a\';else if(e.ctrlKey&&e.key.toLowerCase()===\'l\')data=\'\\x0c\';if(data!==undefined){e.preventDefault();send({type:\'input\',data})}});\n$(\'ctrlC\').onclick=()=>send({type:\'input\',data:\'\\x03\'});$(\'ctrlD\').onclick=()=>send({type:\'input\',data:\'\\x04\'});$(\'clear\').onclick=()=>{$(\'screen\').textContent=\'\'};$(\'disconnect\').onclick=()=>{closeSocket();status(\'Disconnected\')};$(\'logout\').onclick=async()=>{closeSocket();try{await fetch(\'/api/logout\',{method:\'POST\'})}catch{}unlocked=false;$(\'terminalCard\').classList.add(\'hidden\');$(\'loginCard\').classList.remove(\'hidden\');status(\'Locked\')};window.addEventListener(\'resize\',()=>send({type:\'resize\',cols:Math.max(40,Math.floor(window.innerWidth/9)),rows:28}));\n</script></body></html>'
_DASHBOARD_PUBLIC_IP_CACHE = {'checked_at': 0.0, 'value': '', 'source': ''}
_DASHBOARD_PUBLIC_IP_LOCK = asyncio.Lock()
_DASHBOARD_FRAMES = ('◐', '◓', '◑', '◒')

# New features/classes/commands. Legacy definitions remain untouched.

def _load_discord_token() -> str:
    token = _clean_env_value(os.getenv('DISCORD_TOKEN', ''))
    placeholders = {'', 'YOUR_DISCORD_BOT_TOKEN', 'your_discord_bot_token_here', 'YOUR_BOT_TOKEN', 'changeme', 'change_me'}
    if token in placeholders:
        return ''
    if any((ch.isspace() for ch in token)):
        raise RuntimeError('DISCORD_TOKEN contains whitespace. Paste only the raw Bot Token.')
    if not token.isascii():
        raise RuntimeError('DISCORD_TOKEN must contain only ASCII characters. Paste the raw Bot Token, without branding text or symbols.')
    if len(token) < 50:
        raise RuntimeError('DISCORD_TOKEN looks too short. Copy the Bot Token from Discord Developer Portal → Bot.')
    return token
def _is_kvm_vpsctl(path: str) -> bool:
    """Accept only the exact integrity-checked LXD controller bundled with this bot."""
    try:
        payload = Path(path).read_bytes()
        text = payload.decode('utf-8', errors='replace')
        return all((marker in text for marker in KVM_CONTROLLER_MARKERS)) and hashlib.sha256(payload).hexdigest() == _EMBEDDED_VPSCTL_SHA256
    except Exception:
        return False
def _ensure_embedded_kvm_vpsctl() -> Optional[str]:
    """Install the hash-verified embedded LXD controller outside the seven-file bundle.

    Only /usr/local/sbin/vpsctl (or an explicit VPSCTL_PATH) is managed here; no source
    sidecar is created beside bot.py. Existing non-LXD controller files are preserved.
    """
    preferred = VPSCTL_PATH if VPSCTL_PATH and os.path.isabs(VPSCTL_PATH) else '/usr/local/sbin/vpsctl'
    candidates = list(dict.fromkeys([preferred, '/usr/local/sbin/vpsctl', '/usr/local/bin/vpsctl']))
    for raw_target in candidates:
        target = Path(raw_target)
        if target.is_file() and _is_kvm_vpsctl(str(target)):
            return str(target.resolve())
        try:
            payload = zlib.decompress(base64.b64decode(_EMBEDDED_VPSCTL_ZLIB_B64.encode('ascii'), validate=True))
            if hashlib.sha256(payload).hexdigest() != _EMBEDDED_VPSCTL_SHA256:
                raise RuntimeError('embedded LXD controller integrity check failed')
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup = target.with_name(f'{target.name}.legacy-{int(time.time())}')
                try:
                    target.replace(backup)
                except OSError:
                    continue
            temp = target.with_name(f'.{target.name}.rgnodes-{os.getpid()}.tmp')
            try:
                temp.write_bytes(payload)
                os.chmod(temp, 493)
                os.replace(temp, target)
            finally:
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass
            if _is_kvm_vpsctl(str(target)):
                logger.warning('Installed hash-verified embedded LXD controller at %s.', target)
                return str(target.resolve())
        except Exception as exc:
            logger.debug('LXD controller install attempt failed for %s: %s', target, exc)
    logger.error('Could not install the embedded LXD controller; run setup.sh as root and verify /usr/local/sbin is writable.')
    return None
def _find_kvm_vpsctl() -> Optional[str]:
    """Return a trusted LXD controller or safely install the embedded copy."""
    for candidate in VPSCTL_CANDIDATES:
        if candidate and Path(candidate).is_file() and _is_kvm_vpsctl(candidate):
            return str(Path(candidate).resolve())
    return _ensure_embedded_kvm_vpsctl()
def _migrate_legacy_data() -> None:
    """One-time, non-destructive import of data from the old in-repo layout.

    The legacy files are COPIED (SQLite online-backup API for the DB) and never deleted.
    Nothing is migrated if the new database already exists.
    """
    if DATA_DIR == BASE_DIR:
        return
    legacy_db = BASE_DIR / 'vps.db'
    if legacy_db.is_file() and (not Path(DB_FILE).exists()):
        try:
            src = sqlite3.connect(str(legacy_db), timeout=30)
            try:
                dst = sqlite3.connect(DB_FILE)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
            os.chmod(DB_FILE, 384)
            print(f'[AXIONHOST] Migrated legacy database {legacy_db} -> {DB_FILE} (original kept).', file=sys.stderr)
        except Exception as exc:
            try:
                Path(DB_FILE).unlink()
            except OSError:
                pass
            print(f'[AXIONHOST] WARNING: legacy database migration failed: {exc}', file=sys.stderr)
    for legacy_dir, new_dir in ((BASE_DIR / 'db_backups', DB_BACKUP_DIR), (BASE_DIR / VPS_BACKUP_DIR_NAME, VPS_BACKUP_DIR)):
        try:
            if legacy_dir.is_dir() and legacy_dir.resolve() != new_dir.resolve():
                for item in legacy_dir.iterdir():
                    target = new_dir / item.name
                    if item.is_file() and (not target.exists()):
                        shutil.copy2(item, target)
        except Exception as exc:
            print(f'[AXIONHOST] WARNING: could not copy legacy backups from {legacy_dir}: {exc}', file=sys.stderr)
def backup_database():
    """Create a consistent SQLite backup without noisy console output."""
    try:
        if not os.path.exists(DB_FILE):
            return
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = DB_BACKUP_DIR / f'vps_backup_{timestamp}.db'
        with DB_LOCK:
            source = get_db()
            try:
                destination = sqlite3.connect(str(backup_path))
                try:
                    source.backup(destination)
                finally:
                    destination.close()
            finally:
                source.close()
    except Exception as e:
        logger.error(f'Database backup failed: {e}')
def _decode_vps_row(row) -> Dict[str, Any]:
    vps = dict(row)
    try:
        vps['shared_with'] = json.loads(vps.get('shared_with') or '[]')
        if not isinstance(vps['shared_with'], list):
            vps['shared_with'] = []
    except (TypeError, ValueError, json.JSONDecodeError):
        vps['shared_with'] = []
    try:
        vps['suspension_history'] = json.loads(vps.get('suspension_history') or '[]')
        if not isinstance(vps['suspension_history'], list):
            vps['suspension_history'] = []
    except (TypeError, ValueError, json.JSONDecodeError):
        vps['suspension_history'] = []
    vps['suspended'] = bool(vps.get('suspended', 0))
    vps['whitelisted'] = bool(vps.get('whitelisted', 0))
    vps['os_version'] = vps.get('os_version') or 'ubuntu:22.04'
    vps['pinggy_host'] = vps.get('pinggy_host') or None
    try:
        vps['pinggy_port'] = int(vps.get('pinggy_port') or 0) or None
    except (TypeError, ValueError):
        vps['pinggy_port'] = None
    vps['pinggy_url'] = vps.get('pinggy_url') or None
    try:
        vps['pinggy_pid'] = int(vps.get('pinggy_pid') or 0) or None
    except (TypeError, ValueError):
        vps['pinggy_pid'] = None
    vps['pinggy_started_at'] = vps.get('pinggy_started_at') or None
    vps['bandwidth_gb'] = VPS_BANDWIDTH_GB
    try:
        vps['bandwidth_used_bytes'] = max(0, int(vps.get('bandwidth_used_bytes') or 0))
    except (TypeError, ValueError):
        vps['bandwidth_used_bytes'] = 0
    vps['bandwidth_cycle_start'] = vps.get('bandwidth_cycle_start') or datetime.now().isoformat()
    for _bw_key in ('bandwidth_last_rx_bytes', 'bandwidth_last_tx_bytes'):
        try:
            vps[_bw_key] = max(0, int(vps.get(_bw_key) or 0))
        except (TypeError, ValueError):
            vps[_bw_key] = 0
    vps['bandwidth_last_sample_at'] = vps.get('bandwidth_last_sample_at') or None
    vps['ssh_ready'] = bool(vps.get('ssh_ready', 0))
    try:
        vps['vmid'] = int(vps.get('vmid') or vps.get('id') or 0)
    except (TypeError, ValueError):
        vps['vmid'] = 0
    raw_expiration = vps.get('expiration_date')
    if raw_expiration:
        try:
            datetime.fromisoformat(str(raw_expiration))
        except (TypeError, ValueError):
            logger.warning(f"Invalid expiration_date for {vps.get('container_name')}; clearing corrupt value")
            vps['expiration_date'] = None
    return vps
def reserve_vps_vmid() -> int:
    """Reserve a globally unique persistent VPS ID."""
    with DB_LOCK:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute('INSERT INTO vps_vmid_sequence (reserved_at) VALUES (CURRENT_TIMESTAMP)')
            vmid = int(cur.lastrowid)
            conn.commit()
            return vmid
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
def save_admin_data_immediate():
    try:
        save_admin_data()
    except Exception as e:
        logger.error(f'Critical admin database save failed: {e}')
        backup_database()
def ensure_user_port_allocation(user_id: str) -> int:
    """Create the default quota only when no quota row exists; preserve explicit zero quotas."""
    user_id = str(user_id)
    with DB_LOCK:
        conn = get_db()
        try:
            row = conn.execute('SELECT allocated_ports FROM port_allocations WHERE user_id = ?', (user_id,)).fetchone()
            if row is not None:
                return int(row[0] or 0)
            quota = max(0, int(DEFAULT_PORT_QUOTA))
            conn.execute('INSERT INTO port_allocations (user_id, allocated_ports, last_modified) VALUES (?, ?, CURRENT_TIMESTAMP)', (user_id, quota))
            conn.commit()
            return quota
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
def _host_port_in_use(host_port: int) -> bool:
    """Return True when a TCP or UDP listener already occupies the port."""
    for sock_type, proto_name in ((socket.SOCK_STREAM, 'tcp'), (socket.SOCK_DGRAM, 'udp')):
        s = socket.socket(socket.AF_INET, sock_type)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('0.0.0.0', host_port))
        except OSError:
            return True
        finally:
            s.close()
    return False
async def get_container_addresses(container_name: str, node_id: Optional[int]=None) -> Dict[str, List[str]]:
    """Return actual guest IPv4 and globally-scoped IPv6 addresses."""
    if node_id is None:
        node_id = find_node_id_for_container(container_name)
    result: Dict[str, List[str]] = {'ipv4': [], 'ipv6': []}
    try:
        v4 = await execute_vpsctl_compat(container_name, f'exec {container_name} -- ip -4 -o addr show scope global', timeout=20, node_id=node_id)
        for line in str(v4 or '').splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[2] == 'inet':
                addr = parts[3].split('/', 1)[0]
                if addr and addr not in result['ipv4'] and (not addr.startswith('127.')):
                    result['ipv4'].append(addr)
    except Exception as e:
        logger.debug(f'IPv4 discovery failed for {container_name}: {e}')
    try:
        v6 = await execute_vpsctl_compat(container_name, f'exec {container_name} -- ip -6 -o addr show scope global', timeout=20, node_id=node_id)
        for line in str(v6 or '').splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[2] == 'inet6':
                addr = parts[3].split('/', 1)[0]
                if addr and addr not in result['ipv6'] and (addr != '::1') and (not addr.lower().startswith('fe80:')):
                    result['ipv6'].append(addr)
    except Exception as e:
        logger.debug(f'IPv6 discovery failed for {container_name}: {e}')
    return result
async def detect_public_endpoints(node_id: int, vps_name: Optional[str]=None) -> Dict[str, str]:
    """Return real public endpoints. For a VPS, only advertise the guest's own global IPs."""

    def valid_v4(value: str) -> bool:
        try:
            import ipaddress
            ip = ipaddress.ip_address(value.strip())
            return ip.version == 4 and ip.is_global and (not ip.is_multicast) and (not ip.is_reserved) and (not ip.is_unspecified) and (not ip.is_loopback) and (not ip.is_link_local)
        except Exception:
            return False

    def valid_v6(value: str) -> bool:
        try:
            import ipaddress
            ip = ipaddress.ip_address(value.strip())
            return ip.version == 6 and ip.is_global and (not ip.is_multicast) and (not ip.is_reserved) and (not ip.is_unspecified) and (not ip.is_loopback) and (not ip.is_link_local)
        except Exception:
            return False
    if vps_name:
        try:
            addresses = await get_container_addresses(vps_name, node_id)
            v4 = next((x for x in addresses.get('ipv4', []) if valid_v4(x)), '')
            v6 = next((x for x in addresses.get('ipv6', []) if valid_v6(x)), '')
            if v4 or v6:
                return {'ipv4': v4, 'ipv6': v6}
        except Exception as exc:
            logger.debug('VPS public endpoint discovery failed for %s: %s', vps_name, exc)
        node = get_node(node_id) or {}
        if KVM_NETWORK_MODE == 'lxd-managed' and (not node.get('is_local')):
            try:
                response = await asyncio.to_thread(requests.get, str(node.get('url') or '').rstrip('/') + '/api/get_access_info', headers={'X-API-Key': str(node.get('api_key') or '')}, timeout=5)
                if response.status_code == 200:
                    payload = response.json()
                    host_v4 = str(payload.get('public_ipv4') or '').strip()
                    host_v6 = str(payload.get('public_ipv6') or '').strip()
                    return {'ipv4': host_v4 if valid_v4(host_v4) else '', 'ipv6': host_v6 if valid_v6(host_v6) else ''}
            except Exception as exc:
                logger.debug('LXD node public endpoint discovery failed: %s', type(exc).__name__)
        return {'ipv4': '', 'ipv6': ''}
    node = get_node(node_id) or {}
    if node.get('is_local'):
        v4 = PUBLIC_IPV4 if valid_v4(PUBLIC_IPV4) else ''
        v6 = PUBLIC_IPV6 if valid_v6(PUBLIC_IPV6) else ''
        if AUTO_DETECT_PUBLIC_IP and (not v4):
            try:
                r = await asyncio.to_thread(requests.get, 'https://api4.ipify.org', timeout=3)
                candidate = r.text.strip()
                if valid_v4(candidate):
                    v4 = candidate
            except Exception:
                pass
        if AUTO_DETECT_PUBLIC_IP and (not v6):
            try:
                r = await asyncio.to_thread(requests.get, 'https://api6.ipify.org', timeout=3)
                candidate = r.text.strip()
                if valid_v6(candidate):
                    v6 = candidate
            except Exception:
                pass
        return {'ipv4': v4, 'ipv6': v6}
    url = str(node.get('url') or '').rstrip('/') + '/api/get_access_info'
    headers = {'X-API-Key': str(node.get('api_key') or '')}
    try:
        response = await asyncio.to_thread(requests.get, url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        remote_v4 = str(data.get('public_ipv4') or '').strip()
        remote_v6 = str(data.get('public_ipv6') or '').strip()
        return {'ipv4': remote_v4 if valid_v4(remote_v4) else '', 'ipv6': remote_v6 if valid_v6(remote_v6) else ''}
    except Exception as e:
        logger.debug('Node endpoint discovery failed on %s: %s', node.get('name'), e)
        return {'ipv4': '', 'ipv6': ''}
def format_public_ssh_access(endpoints: Dict[str, str], ssh_port: Optional[int]) -> Dict[str, str]:
    result = {'ipv4': str(endpoints.get('ipv4') or ''), 'ipv6': str(endpoints.get('ipv6') or ''), 'ssh_ipv4': '', 'ssh_ipv6': ''}
    try:
        port = int(ssh_port or 0)
    except (TypeError, ValueError):
        port = 0
    if port and result['ipv4']:
        result['ssh_ipv4'] = 'ssh root@{} -p {}'.format(result['ipv4'], port)
    if port and result['ipv6']:
        result['ssh_ipv6'] = 'ssh -6 root@[{}] -p {}'.format(result['ipv6'], port)
    return result
async def get_container_network_counters(container_name: str, node_id: Optional[int]=None) -> tuple[int, int]:
    """Return aggregate RX/TX byte counters for non-loopback guest interfaces."""
    if node_id is None:
        node_id = find_node_id_for_container(container_name)
    script = 'set +e\nrx=0; tx=0\nwhile IFS= read -r line; do\n  iface=${line%%:*}\n  rest=${line#*:}\n  iface=$(echo "$iface" | xargs)\n  [ -n "$iface" ] || continue\n  [ "$iface" = "lo" ] && continue\n  read -r -a f <<< "$rest"\n  [ "${#f[@]}" -ge 9 ] || continue\n  [[ "${f[0]}" =~ ^[0-9]+$ ]] || continue\n  [[ "${f[8]}" =~ ^[0-9]+$ ]] || continue\n  rx=$((rx + f[0])); tx=$((tx + f[8]))\ndone < /proc/net/dev\nprintf \'%s %s\\n\' "$rx" "$tx"\n'
    output = await _exec_guest_bash(container_name, node_id, script, timeout=20)
    parts = str(output or '').strip().split()
    if len(parts) < 2:
        raise RuntimeError('Guest network counters unavailable')
    return (max(0, int(parts[0])), max(0, int(parts[1])))
def _human_bytes(n: int) -> str:
    n = float(max(0, int(n)))
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f'{n:.1f} {units[i]}' if i else f'{int(n)} B'
async def get_container_network_usage(container_name: str, node_id: Optional[int]=None) -> tuple[str, str]:
    """Return aggregate RX/TX byte counters as readable strings."""
    try:
        rx, tx = await get_container_network_counters(container_name, node_id)
        return (_human_bytes(rx), _human_bytes(tx))
    except Exception:
        return ('N/A', 'N/A')
async def get_container_docker_status(container_name: str, node_id: Optional[int]=None) -> str:
    """Report the actual Docker state instead of claiming Docker is ready from guest hardening alone."""
    try:
        out = await _exec_guest_bash(container_name, node_id, "set +e\nif ! command -v docker >/dev/null 2>&1; then\n  printf 'UNINSTALLED\n'\n  exit 0\nfi\nif docker info >/dev/null 2>&1; then\n  printf 'READY\n'\nelif systemctl is-active --quiet docker 2>/dev/null; then\n  printf 'DAEMON_WAIT\n'\nelse\n  printf 'STOPPED\n'\nfi\n", timeout=25)
        state = str(out or '').strip().splitlines()[-1:]
        state = state[0] if state else 'UNKNOWN'
        return {'READY': '🐳 Ready', 'DAEMON_WAIT': '🐳 Starting', 'STOPPED': '🐳 Stopped', 'UNINSTALLED': '⚪ Not Installed'}.get(state, '⚪ Unknown')
    except Exception:
        return '⚪ Unavailable'
async def ensure_docker_ready(container_name: str, node_id: int, strict: bool=False) -> bool:
    """Install Docker with distro packages first, then Docker's official repository fallback, and verify daemon readiness."""
    script = 'set -Eeuo pipefail\nexport DEBIAN_FRONTEND=noninteractive\n\nverify() {\n  command -v docker >/dev/null 2>&1 || return 1\n  docker info >/dev/null 2>&1 || return 1\n  docker version --format \'{{.Server.Version}}\' >/dev/null 2>&1 || return 1\n  return 0\n}\n\nif verify; then\n  printf \'READY\\n\'; exit 0\nfi\n\napt update -qq\napt install -y ca-certificates curl gnupg >/dev/null\n\n# First try the distribution package because it is simplest inside LXD VPS.\nif apt-cache show docker.io >/dev/null 2>&1; then\n  apt install -y docker.io >/dev/null 2>&1 || true\nfi\n\n# Official Docker repository fallback for Debian/Ubuntu where docker.io is unavailable/broken.\nif ! command -v docker >/dev/null 2>&1; then\n  install -m 0755 -d /etc/apt/keyrings\n  . /etc/os-release\n  case "$ID" in\n    ubuntu|debian)\n      curl -fsSL "https://download.docker.com/linux/$ID/gpg" | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg\n      chmod a+r /etc/apt/keyrings/docker.gpg\n      arch="$(dpkg --print-architecture)"\n      if [ "$ID" = "ubuntu" ]; then\n        codename="${VERSION_CODENAME:-$(. /etc/os-release; printf \'%s\' "${UBUNTU_CODENAME:-}")}"\n      else\n        codename="${VERSION_CODENAME:-$(. /etc/os-release; printf \'%s\' "${VERSION_CODENAME:-}")}"\n      fi\n      [ -n "$codename" ] || codename="stable"\n      printf \'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/%s %s stable\\n\' "$arch" "$ID" "$codename" > /etc/apt/sources.list.d/docker.list\n      apt update -qq\n      apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null 2>&1 || true\n      ;;\n  esac\nfi\n\n# Fallback to any docker package discovered after repo setup.\nif ! command -v docker >/dev/null 2>&1 && apt-cache show docker.io >/dev/null 2>&1; then\n  apt install -y docker.io >/dev/null 2>&1 || true\nfi\n\nif ! command -v docker >/dev/null 2>&1; then\n  printf \'UNINSTALLED\\n\'\n  exit 21\nfi\n\n# LXD VPS commonly runs without a usable systemd PID 1. Prefer the distro service when available.\nif command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files docker.service >/dev/null 2>&1; then\n  systemctl enable docker >/dev/null 2>&1 || true\n  systemctl start docker >/dev/null 2>&1 || true\nfi\nif command -v service >/dev/null 2>&1; then\n  service docker start >/dev/null 2>&1 || true\nfi\n\n# If dockerd is installed but not running, launch a guest daemon only when safe and no daemon exists.\nif ! docker info >/dev/null 2>&1 && command -v dockerd >/dev/null 2>&1; then\n  if ! pgrep -x dockerd >/dev/null 2>&1; then\n    nohup dockerd >/var/log/rgnodes-dockerd.log 2>&1 &\n    sleep 2\n  fi\nfi\n\nfor _ in $(seq 1 25); do\n  if verify; then printf \'READY\\n\'; exit 0; fi\n  sleep 1\ndone\nprintf \'NOT_READY\\n\'\nexit 22\n'
    try:
        output = await _exec_guest_bash(container_name, node_id, script, timeout=210)
        ready = str(output or '').strip().splitlines()[-1:] == ['READY']
        if strict and (not ready):
            raise RuntimeError(f'Docker could not be verified inside {container_name}.')
        return ready
    except Exception:
        if strict:
            raise
        return False
def is_admin_user(user_or_member: int | str | object) -> bool:
    obj = user_or_member
    uid = str(getattr(obj, 'id', obj))
    if uid == str(MAIN_ADMIN_ID) or uid in {str(x) for x in admin_data.get('admins', [])} or uid in set(CONFIG_ADMIN_IDS):
        return True
    perms = getattr(obj, 'guild_permissions', None)
    return bool(perms is not None and getattr(perms, 'administrator', False))
def maintenance_enabled() -> bool:
    return str(get_setting('maintenance', 'off')).strip().lower() == 'on'
def maintenance_applies_to_user(user_id: int | str) -> bool:
    """Maintenance is user-facing; administrators remain fully operational."""
    return maintenance_enabled() and (not is_admin_user(user_id))
def user_has_vps(user_id: int | str) -> bool:
    return bool(vps_data.get(str(user_id), []))
def find_vps_record(reference: str | int):
    """Resolve a VPS by container name or numeric persistent VPS ID."""
    wanted = str(reference).strip()
    numeric_id = int(wanted) if wanted.isdigit() else None
    for uid, items in vps_data.items():
        for idx, vps in enumerate(items):
            same_name = str(vps.get('container_name')) == wanted
            same_id = numeric_id is not None and (int(vps.get('id', -1) or -1) == numeric_id or int(vps.get('vmid', -1) or -1) == numeric_id)
            if same_name or same_id:
                return (str(uid), idx, vps)
    return (None, None, None)
def suspended_due_to_expiration(vps: Dict[str, Any]) -> bool:
    """Return True only when the latest suspension was caused by expiration."""
    if not vps.get('suspended'):
        return False
    history = vps.get('suspension_history') or []
    if not isinstance(history, list) or not history:
        return False
    latest = history[-1]
    if not isinstance(latest, dict):
        return False
    by = str(latest.get('by') or '').lower()
    reason = str(latest.get('reason') or '').lower()
    return 'expiration' in by or 'expired' in reason or 'expiration' in reason
async def ensure_vps_image_remote(remote: str, node_id: int) -> None:
    """Compatibility no-op retained for legacy callers; VPS images are downloaded cloud images."""
    return None
async def _image_matches(node_id: int, remote: str, terms: list[str]) -> list[str]:
    return []
async def resolve_vps_image(os_value: str, node_id: int) -> str:
    """Resolve to a supported cloud-image identifier used by the LXD controller."""
    raw = str(os_value or '').strip().lower()
    aliases = {'ubuntu:focal': 'ubuntu:20.04', 'ubuntu:jammy': 'ubuntu:22.04', 'ubuntu:noble': 'ubuntu:24.04', 'ubuntu/focal': 'ubuntu:20.04', 'ubuntu/jammy': 'ubuntu:22.04', 'ubuntu/noble': 'ubuntu:24.04', 'ubuntu/focal/desktop': 'ubuntu:20.04', 'ubuntu/jammy/desktop': 'ubuntu:22.04', 'ubuntu/noble/desktop': 'ubuntu:24.04', 'ubuntu:jammy/desktop': 'ubuntu:22.04', 'ubuntu:focal/desktop': 'ubuntu:20.04', 'ubuntu:noble/desktop': 'ubuntu:24.04', 'ubuntu/jammy/server': 'ubuntu:22.04', 'ubuntu/focal/server': 'ubuntu:20.04', 'ubuntu/noble/server': 'ubuntu:24.04', 'images:ubuntu/20.04': 'ubuntu:20.04', 'images:ubuntu/22.04': 'ubuntu:22.04', 'images:ubuntu/24.04': 'ubuntu:24.04', 'images:debian/11': 'debian:11', 'images:debian/12': 'debian:12', 'images:debian/13': 'debian:13', 'debian:11': 'debian:11', 'debian:12': 'debian:12', 'debian:13': 'debian:13'}
    resolved = aliases.get(raw, raw)
    supported = {'ubuntu:20.04', 'ubuntu:22.04', 'ubuntu:24.04', 'debian:11', 'debian:12', 'debian:13'}
    if resolved not in supported:
        raise RuntimeError(f'Unsupported VPS OS image: {os_value}. Supported images: Ubuntu 20.04/22.04/24.04 and Debian 11/12/13.')
    return resolved
def friendly_os_label(os_value: str) -> str:
    """Convert supported cloud-image identifiers into a compact OS label."""
    raw = str(os_value or 'Unknown').strip()
    aliases = {'ubuntu:20.04': 'Ubuntu 20.04 LTS', 'ubuntu:22.04': 'Ubuntu 22.04 LTS', 'ubuntu:24.04': 'Ubuntu 24.04 LTS', 'images:ubuntu/20.04': 'Ubuntu 20.04 LTS', 'images:ubuntu/22.04': 'Ubuntu 22.04 LTS', 'images:ubuntu/24.04': 'Ubuntu 24.04 LTS', 'images:debian/11': 'Debian 11', 'images:debian/12': 'Debian 12', 'images:debian/13': 'Debian 13', 'debian:11': 'Debian 11', 'debian:12': 'Debian 12', 'debian:13': 'Debian 13'}
    return aliases.get(raw, raw)
def location_flag(location: str) -> str:
    flags = {'India': '🇮🇳', 'SG': '🇸🇬', 'Singapore': '🇸🇬', 'Bangladesh': '🇧🇩', 'US': '🇺🇸', 'USA': '🇺🇸'}
    return flags.get(str(location or '').strip(), '🌐')
async def auto_fit_vps_resources(node_id: int, requested_ram_gb: int, requested_cpu: int, requested_disk_gb: int) -> tuple[int, int, int, str]:
    """Derive a safe, non-overcommitting VPS plan from live node capacity.

    RAM is capped at MAX_VPS_RAM_GB (hard ceiling 22 GiB by default) and is
    reduced to what the host can safely provide after its reserve. CPU is capped
    to the configured maximum and the host's protected CPU reserve. Disk remains
    the requested value because LXD storage pool quotas; the
    normal admission check still enforces real free-space reserve.
    """
    requested_ram_gb = max(MIN_VPS_RAM_GB, min(MAX_VPS_RAM_GB, int(requested_ram_gb)))
    requested_cpu = max(1, min(MAX_VPS_CPU, int(requested_cpu)))
    requested_disk_gb = max(5, int(requested_disk_gb))
    if not AUTO_RESOURCE_ALLOCATION:
        return (requested_ram_gb, requested_cpu, requested_disk_gb, 'Automatic resource fitting is disabled.')
    stats = await get_host_stats(node_id)
    total = int(stats.get('ram_bytes_total') or 0)
    available = int(stats.get('ram_bytes_available') or max(0, total - int(stats.get('ram_bytes_used') or 0)))
    allocated = sum((_parse_gb(v.get('ram', '0GB'), 0) for items in vps_data.values() for v in items if int(v.get('node_id', 1)) == int(node_id) and (not bool(v.get('suspended', False)))))
    safe_bytes = max(0, available - int(HOST_RAM_RESERVE_GB * 1024 ** 3))
    share_bytes = max(0, int(total * MAX_DEPLOY_RAM_SHARE) - int(allocated * 1024 ** 3)) if total else safe_bytes
    fit_ram = min(requested_ram_gb, MAX_VPS_RAM_GB, safe_bytes // 1024 ** 3, share_bytes // 1024 ** 3)
    if fit_ram < MIN_VPS_RAM_GB:
        fit_ram = 0
    cpu_total = int(stats.get('cpu_count') or 0)
    allocated_cpu = sum((_parse_cpu(v.get('cpu', 0), 0) for items in vps_data.values() for v in items if int(v.get('node_id', 1)) == int(node_id) and (not bool(v.get('suspended', False)))))
    cpu_budget = max(0, int(cpu_total * HOST_VCPU_OVERCOMMIT_RATIO) - max(0, env_int('HOST_CPU_RESERVE', '1')) - allocated_cpu) if cpu_total else requested_cpu
    fit_cpu = min(requested_cpu, MAX_VPS_CPU, cpu_budget)
    if fit_cpu < 1:
        fit_cpu = 0
    if not fit_ram or not fit_cpu:
        return (0, 0, requested_disk_gb, f'The node has insufficient safe headroom for a new VPS. Requested up to {requested_ram_gb} GiB / {requested_cpu} CPU, but the protected host budget cannot provide at least {MIN_VPS_RAM_GB} GiB / 1 CPU.')
    reason = f'Auto-fit enabled • allocated {allocated} GiB RAM / {allocated_cpu} CPU on node • selected {fit_ram} GiB RAM / {fit_cpu} CPU • hard RAM ceiling {MAX_VPS_RAM_GB} GiB.'
    return (fit_ram, fit_cpu, requested_disk_gb, reason)
async def check_node_capacity_for_vps(node_id: int, ram_gb: int, cpu_cores: int, disk_gb: int) -> tuple[bool, str]:
    """Conservative admission control: protect the main host from RAM/CPU/disk exhaustion."""
    node = get_node(node_id)
    if not node:
        return (False, f'Node {node_id} not found.')
    try:
        stats = await asyncio.wait_for(get_host_stats(node_id), timeout=15)
    except Exception as exc:
        return (False, safe_error_summary('Node health check', exc))
    cpu = float(stats.get('cpu') or 0.0)
    ram_pct = float(stats.get('ram') or 0.0)
    total = int(stats.get('ram_bytes_total') or 0)
    available = int(stats.get('ram_bytes_available') or max(0, total - int(stats.get('ram_bytes_used') or 0)))
    disk_free = int(stats.get('disk_free') or 0)
    if total:
        requested = int(float(ram_gb) * 1024 ** 3)
        reserve = int(HOST_RAM_RESERVE_GB * 1024 ** 3)
        max_guest = int(total * MAX_DEPLOY_RAM_SHARE)
        allocated_ram = sum((_parse_gb(v.get('ram', '0GB'), 0) for items in vps_data.values() for v in items if int(v.get('node_id', 1)) == int(node_id) and (not bool(v.get('suspended', False)))))
        allocated_bytes = allocated_ram * 1024 ** 3
        if requested > max_guest or allocated_bytes + requested + reserve > max_guest:
            return (False, f'Host RAM allocation guard blocked deployment: allocated {allocated_ram} GiB + requested {ram_gb} GiB exceeds the safe host budget. {HOST_PROVIDER_NAME} is protected.')
        if available < requested + reserve:
            return (False, f'Host safety guard blocked deployment: available RAM {available / 1024 ** 3:.1f} GiB; requested {ram_gb} GiB + reserve {HOST_RAM_RESERVE_GB:.1f} GiB.')
        if ram_pct > 100.0 - MIN_HOST_RAM_FREE_PCT_DEPLOY:
            return (False, f'Host RAM is {ram_pct:.1f}% used. Deployment is paused until at least {MIN_HOST_RAM_FREE_PCT_DEPLOY:.0f}% RAM is free.')
    cpu_total = int(stats.get('cpu_count') or 0)
    if cpu_total:
        allocated_cpu = sum((_parse_cpu(v.get('cpu', 0), 0) for items in vps_data.values() for v in items if int(v.get('node_id', 1)) == int(node_id) and (not bool(v.get('suspended', False)))))
        if allocated_cpu + int(cpu_cores) > max(1, int(cpu_total * HOST_VCPU_OVERCOMMIT_RATIO) - max(0, env_int('HOST_CPU_RESERVE', '1'))):
            return (False, f'Host CPU allocation guard blocked deployment: allocated {allocated_cpu} cores + requested {cpu_cores} cores would consume the protected CPU reserve.')
    if cpu >= HOST_CPU_MAX_DEPLOY_PCT:
        return (False, f'Host CPU is {cpu:.1f}% used. Deployment is paused below {HOST_CPU_MAX_DEPLOY_PCT:.0f}% to protect {HOST_PROVIDER_NAME}.')
    if disk_free:
        disk_reserve_bytes = int(HOST_DISK_RESERVE_GB * 1024 ** 3)
        requested_disk_bytes = int(float(disk_gb) * 1024 ** 3)
        allocated_disk = sum((_parse_gb(v.get('storage', '0GB'), 0) for items in vps_data.values() for v in items if int(v.get('node_id', 1)) == int(node_id) and (not bool(v.get('suspended', False)))))
        disk_total = int(stats.get('disk_total') or 0)
        if disk_total and (allocated_disk + float(disk_gb)) * 1024 ** 3 + disk_reserve_bytes > disk_total:
            return (False, f'Host disk allocation guard blocked deployment: allocated {allocated_disk} GiB + requested {disk_gb} GiB exceeds the protected host budget.')
        if disk_free < requested_disk_bytes + disk_reserve_bytes:
            return (False, f'Host disk safety guard blocked deployment: only {disk_free / 1024 ** 3:.1f} GiB free; request {disk_gb} GiB + reserve {HOST_DISK_RESERVE_GB:.1f} GiB.')
    return (True, f'Host healthy • CPU {cpu:.1f}% • RAM {ram_pct:.1f}% • disk reserve active • {HOST_PROVIDER_NAME}.')
async def check_node_capacity_for_start(node_id: int, container_name: str, ram_gb: int, cpu_cores: int) -> tuple[bool, str]:
    """Preflight a START operation without double-counting the stopped target VPS."""
    node = get_node(node_id)
    if not node:
        return (False, f'Node {node_id} not found.')
    try:
        stats = await asyncio.wait_for(get_host_stats(node_id), timeout=12)
    except Exception as exc:
        return (False, safe_error_summary('Host health check', exc))
    cpu = float(stats.get('cpu') or 0.0)
    total = int(stats.get('ram_bytes_total') or 0)
    available = int(stats.get('ram_bytes_available') or max(0, total - int(stats.get('ram_bytes_used') or 0)))
    if total:
        requested = int(float(ram_gb) * 1024 ** 3)
        reserve = int(HOST_RAM_RESERVE_GB * 1024 ** 3)
        if available < requested + reserve:
            return (False, f'Start blocked to protect {HOST_PROVIDER_NAME}: only {available / 1024 ** 3:.1f} GiB RAM is available; VPS needs {ram_gb} GiB plus {HOST_RAM_RESERVE_GB:.1f} GiB reserve.')
        if float(stats.get('ram') or 0.0) > 100.0 - MIN_HOST_RAM_FREE_PCT_DEPLOY:
            return (False, f"Start blocked: host RAM is {float(stats.get('ram') or 0.0):.1f}% used.")
    if cpu >= HOST_CPU_MAX_DEPLOY_PCT:
        return (False, f'Start blocked: host CPU is {cpu:.1f}% used. {HOST_PROVIDER_NAME} safety threshold is {HOST_CPU_MAX_DEPLOY_PCT:.0f}%.')
    cpu_total = int(stats.get('cpu_count') or 0)
    if cpu_total:
        allocated = 0
        for items in vps_data.values():
            for v in items:
                if int(v.get('node_id', 1)) != int(node_id) or bool(v.get('suspended', False)):
                    continue
                if str(v.get('container_name')) == str(container_name):
                    continue
                if str(v.get('status', '')).lower() == 'running':
                    allocated += _parse_cpu(v.get('cpu', 0), 0)
        if allocated + int(cpu_cores) > max(1, int(cpu_total * HOST_VCPU_OVERCOMMIT_RATIO) - max(0, env_int('HOST_CPU_RESERVE', '1'))):
            return (False, f'Start blocked by CPU allocation guard: {allocated} running cores + {cpu_cores} requested would exceed the protected host CPU reserve.')
    return (True, f'Host start preflight passed • CPU {cpu:.1f}% • RAM available {available / 1024 ** 3:.1f} GiB.')
async def send_progress(progress_message: discord.Message, title: str, step: int, total: int, detail: str, *, active_index: Optional[int]=None, frame: int=0, failed: bool=False, vps_name: str='rgnodes-vps'):
    """Update the persistent colorless deployment card with an animated, truthful checklist."""
    total = max(1, int(total))
    completed = max(0, min(int(step), total))
    stages = DEPLOYMENT_STAGES if total == len(DEPLOYMENT_STAGES) else [f'Deployment step {i + 1}' for i in range(total)]
    if active_index is None:
        active_index = min(completed, total - 1)
    active_index = max(0, min(int(active_index), total - 1))
    spinner = _DEPLOY_SPINNER_FRAMES[int(frame) % len(_DEPLOY_SPINNER_FRAMES)]
    pct = int(completed / total * 100)
    filled = int(20 * completed / total)
    static_bar = '▰' * filled + '▱' * (20 - filled)
    moving = ['▱'] * 9
    moving[int(frame) % len(moving)] = '▰'
    animated_bar = ''.join(moving)
    checklist = []
    for idx, stage in enumerate(stages):
        if idx < completed:
            marker = '✅'
        elif failed and idx == active_index:
            marker = '❌'
        elif idx == active_index and completed < total:
            marker = spinner
        else:
            marker = '▫️'
        checklist.append(f'{marker} {stage}')
    detail_text = truncate_text(detail, 1100)
    description = f'**VPS:** `{truncate_text(vps_name, 80)}`\n`[{static_bar}]` **{pct}%** · `{completed}/{total} stages complete`\n`[{animated_bar}]` {spinner} **{truncate_text(title, 120)}**\n\n{chr(10).join(checklist)}\n\n{detail_text}'
    embed = create_info_embed(f'{spinner} Deploying VPS', description)
    try:
        await progress_message.edit(embed=embed, view=None, allowed_mentions=discord.AllowedMentions.none())
    except Exception as exc:
        logger.warning('Could not update public VPS deployment progress message %s: %s', getattr(progress_message, 'id', 'unknown'), type(exc).__name__)
async def run_deployment_stage(progress_message: discord.Message, stage_index: int, detail: str, operation, vps_name: str):
    """Run one real stage while animating the same durable Discord message until it finishes."""
    total = len(DEPLOYMENT_STAGES)
    stage_name = DEPLOYMENT_STAGES[stage_index]
    await send_progress(progress_message, stage_name, stage_index, total, detail, active_index=stage_index, frame=0, vps_name=vps_name)
    task = asyncio.create_task(operation(), name=f'rgnodes_deploy_stage_{stage_index + 1}')
    frame = 1
    try:
        while not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=1.35)
            except asyncio.TimeoutError:
                await send_progress(progress_message, stage_name, stage_index, total, f'{detail}\n\nLive check in progress. This stage is not marked complete until its operation returns.', active_index=stage_index, frame=frame, vps_name=vps_name)
                frame += 1
        result = await task
    except asyncio.CancelledError:
        task.cancel()
        raise
    except Exception as exc:
        await send_progress(progress_message, stage_name, stage_index, total, f'Stage failed safely ({type(exc).__name__}). The deployment has stopped at this checkpoint; see the diagnostic log for details.', active_index=stage_index, frame=frame, failed=True, vps_name=vps_name)
        raise
    await send_progress(progress_message, stage_name, stage_index + 1, total, f'✅ Stage verified: {detail}', active_index=min(stage_index + 1, total - 1), frame=frame, vps_name=vps_name)
    return result
async def _background_start_pinggy(container_name: str, node_id: int):
    try:
        info = await asyncio.wait_for(start_pinggy_session(container_name, node_id), timeout=120)
        if info:
            logger.info('Pinggy background bootstrap connected for %s; endpoint omitted from logs', container_name)
        else:
            logger.warning('Pinggy background bootstrap did not produce an endpoint for %s; repair loop will retry.', container_name)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning('Pinggy background bootstrap failed for %s: %s', container_name, exc)
async def safe_guest_install(container_name: str, node_id: int):
    """Fast post-boot baseline only; package/tunnel work is deferred to repair workers.

    This function is intentionally kept below the remote node-agent timeout budget so
    creating a VPS cannot fail merely because apt mirrors or tunnel providers are slow.
    """
    await set_guest_hostname(container_name, node_id, VPS_HOSTNAME)
    try:
        await install_anti_mining_guard(container_name, node_id)
    except Exception as exc:
        logger.debug('Anti-mining guard deferred for %s: %s', container_name, exc)
    try:
        await apply_guest_motd(container_name, node_id)
    except Exception as exc:
        logger.debug('MOTD setup deferred for %s: %s', container_name, exc)
async def protection_repair_task():
    """Ensure all currently-running managed VPS have the anti-mining guard installed.

    This repairs VPS created by older bot versions without starting stopped instances.
    The regular Start/Reinstall/Deploy flows also install the guard.
    """
    await bot.wait_until_ready()
    await asyncio.sleep(30)
    while not bot.is_closed():
        try:
            for owner_id, vps_list in list(vps_data.items()):
                for vps in list(vps_list):
                    if bool(vps.get('suspended', False)):
                        continue
                    container = str(vps.get('container_name') or '').strip()
                    if not container:
                        continue
                    node_id = int(vps.get('node_id', 1))
                    try:
                        if str(vps.get('status', 'stopped')).lower() != 'running':
                            continue
                        await install_anti_mining_guard(container, node_id)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.debug(f'Protection repair skipped for {container}: {e}')
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f'Protection repair task failed: {e}', exc_info=True)
        await asyncio.sleep(12 * 3600)
async def guest_baseline_repair_task():
    """Periodically repair only missing guest baseline dependencies on running VPS."""
    await bot.wait_until_ready()
    await asyncio.sleep(90)
    required = 'bash sudo curl ip ss ps python3 test'
    while not bot.is_closed():
        try:
            for _owner_id, items in list(vps_data.items()):
                for vps in list(items):
                    if bool(vps.get('suspended', False)):
                        continue
                    container = str(vps.get('container_name') or '').strip()
                    if not container:
                        continue
                    node_id = int(vps.get('node_id', 1))
                    try:
                        if str(vps.get('status', 'stopped')).lower() != 'running':
                            continue
                        probe = await _exec_guest_bash(container, node_id, 'if [ -e /etc/systemd/system/rgnodes-sshx.service ] || [ -e /etc/cron.d/rgnodes-sshx ] || [ -e /var/lib/rgnodes/sshx.supervisor.pid ] || command -v sshx >/dev/null 2>&1; then if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then systemctl stop rgnodes-sshx.service >/dev/null 2>&1 || true; systemctl disable rgnodes-sshx.service >/dev/null 2>&1 || true; fi; oldpid=$(cat /var/lib/rgnodes/sshx.supervisor.pid 2>/dev/null || true); case "$oldpid" in \'\'|*[!0-9]*) ;; *) kill -TERM "$oldpid" 2>/dev/null || true ;; esac; if [ -s /tmp/sshx.pid ]; then kill "$(cat /tmp/sshx.pid)" >/dev/null 2>&1 || true; fi; rm -f /tmp/sshx.pid; rm -f /etc/systemd/system/rgnodes-sshx.service /etc/cron.d/rgnodes-sshx /usr/local/sbin/rgnodes-sshx-supervisor /usr/local/bin/sshx /usr/bin/sshx /root/.local/bin/sshx /root/.cargo/bin/sshx /var/lib/rgnodes/sshx.url /var/lib/rgnodes/sshx.pid /var/lib/rgnodes/sshx-direct.pid /var/lib/rgnodes/sshx.supervisor.pid /var/lib/rgnodes/sshx.log /var/lib/rgnodes/sshx-tty.log /var/lib/rgnodes/sshx-supervisor.log /var/lib/rgnodes/sshx-install.log; if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then systemctl daemon-reload >/dev/null 2>&1 || true; fi; fi; missing=\'\'; for c in bash sudo curl ip ss ps python3; do command -v "$c" >/dev/null 2>&1 || missing="$missing $c"; done; test -d /etc/ssh/sshd_config.d || missing="$missing sshd-config-dir"; if [ -n "$missing" ]; then printf \'MISSING:%s\\n\' "$missing"; else printf \'OK\\n\'; fi', timeout=25)
                        if str(probe).strip().startswith('MISSING:'):
                            logger.warning(f'Guest baseline repair required for {container}: {probe.strip()}')
                            await bootstrap_vps_guest(container, node_id)
                            await install_anti_mining_guard(container, node_id)
                            await recreate_port_forwards(container, node_id_override=node_id)
                        try:
                            await apply_guest_motd(container, node_id)
                        except Exception as motd_exc:
                            logger.debug(f'MOTD baseline repair skipped for {container}: {motd_exc}')
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.debug(f'Guest baseline repair skipped for {container}: {e}')
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f'Guest baseline repair task failed: {e}', exc_info=True)
        await asyncio.sleep(18 * 3600)
async def access_repair_task():
    """Repair only VPSs that actually need SSH setup or a missing port-forward."""
    await bot.wait_until_ready()
    await asyncio.sleep(45)
    while not bot.is_closed():
        try:
            candidates = []
            for owner_id, items in list(vps_data.items()):
                for vps in list(items):
                    if bool(vps.get('suspended', False)):
                        continue
                    container = str(vps.get('container_name') or '').strip()
                    if not container:
                        continue
                    if str(vps.get('status', 'stopped')).lower() != 'running':
                        continue
                    forwards = [f for f in get_user_forwards(str(owner_id)) if str(f.get('vps_container')) == container and int(f.get('vps_port', 0) or 0) == 22]
                    needs_forward = not forwards
                    needs_ssh = not bool(vps.get('ssh_ready', False))
                    if needs_forward or needs_ssh:
                        candidates.append((str(owner_id), vps, needs_forward, needs_ssh))
            sem = asyncio.Semaphore(MAX_BACKGROUND_REPAIR_CONCURRENCY)

            async def repair_one(owner_id, vps, needs_forward, needs_ssh):
                container = str(vps.get('container_name'))
                node_id = int(vps.get('node_id', 1))
                async with sem:
                    if needs_ssh:
                        password = str(vps.get('root_password') or generate_strong_password())
                        try:
                            ok, result = await asyncio.wait_for(configure_ssh(container, node_id, password), timeout=105)
                            if ok:
                                vps['root_password'] = password
                                vps['ssh_ready'] = True
                                try:
                                    await apply_guest_motd(container, node_id)
                                except Exception:
                                    pass
                                save_vps_data_immediate()
                            else:
                                logger.debug('SSH repair not ready for %s: %s', container, result)
                        except Exception as exc:
                            logger.debug('SSH repair skipped for %s: %s', container, exc)
                    if needs_forward:
                        try:
                            port = await asyncio.wait_for(create_port_forward(owner_id, container, 22, node_id), timeout=75)
                            if port:
                                logger.info('🔧 Repaired SSH port-forward for %s: host %s -> guest 22', container, port)
                        except Exception as exc:
                            logger.debug('SSH port-forward repair skipped for %s: %s', container, exc)
            for start_idx in range(0, len(candidates), 10):
                await asyncio.gather(*(repair_one(*x) for x in candidates[start_idx:start_idx + 10]), return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error('Access repair task failed: %s', exc, exc_info=True)
        await asyncio.sleep(ACCESS_REPAIR_INTERVAL)
async def tunnel_repair_task():
    """Keep Pinggy healthy without probing every VPS with expensive LXD VPS stats."""
    await bot.wait_until_ready()
    await asyncio.sleep(30)
    sem = asyncio.Semaphore(MAX_BACKGROUND_REPAIR_CONCURRENCY)

    async def repair_one(vps):
        if bool(vps.get('suspended', False)) or str(vps.get('status', 'stopped')).lower() != 'running':
            return
        container = str(vps.get('container_name') or '').strip()
        if not container:
            return
        node_id = int(vps.get('node_id', 1))
        async with sem:
            if PINGGY_ENABLED and PINGGY_AUTO_START:
                try:
                    _, _, ok = await asyncio.wait_for(get_pinggy_session_info(container, node_id), timeout=12)
                    if not ok:
                        await asyncio.wait_for(start_pinggy_session(container, node_id), timeout=120)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug('Pinggy repair skipped for %s: %s', container, exc)
    while not bot.is_closed():
        try:
            all_vps = [vps for items in list(vps_data.values()) for vps in list(items)]
            for batch_start in range(0, len(all_vps), 10):
                await asyncio.gather(*(repair_one(v) for v in all_vps[batch_start:batch_start + 10]), return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error('Tunnel repair task failed: %s', exc, exc_info=True)
        await asyncio.sleep(TUNNEL_REPAIR_INTERVAL)
async def expiration_monitor_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await check_vps_expiration()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f'Expiration monitor failed: {e}', exc_info=True)
        await asyncio.sleep(3600)
async def runtime_self_repair_task():
    """Low-risk startup repair: sync DB status and restore security/ports."""
    await bot.wait_until_ready()
    await asyncio.sleep(15)
    try:
        for _owner_id, items in list(vps_data.items()):
            for vps in list(items):
                container = str(vps.get('container_name') or '').strip()
                if not container:
                    continue
                node_id = int(vps.get('node_id', 1))
                try:
                    stats = await asyncio.wait_for(get_container_stats(container, node_id), timeout=12)
                    actual = str(stats.get('status', 'unknown')).lower()
                    if actual in {'running', 'stopped'} and actual != str(vps.get('status', 'stopped')).lower():
                        vps['status'] = actual
                        save_vps_data_immediate()
                    if actual == 'running' and (not bool(vps.get('suspended', False))):
                        await install_anti_mining_guard(container, node_id)
                        await recreate_port_forwards(container, node_id_override=node_id)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.debug(f'Runtime self-repair skipped for {container}: {e}')
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f'Runtime self-repair failed: {e}', exc_info=True)
def _sanitize_command_for_audit(ctx) -> str:
    try:
        content = str(getattr(getattr(ctx, 'message', None), 'content', '') or '').strip()
    except Exception:
        content = ''
    if not content:
        return f"{PREFIX}{getattr(getattr(ctx, 'command', None), 'qualified_name', 'unknown')}"
    content = re.sub('(?i)(password|passwd|token|api[_-]?key|secret)\\s+\\S+', '\\1 [REDACTED]', content)
    content = content[:700]
    return content
@bot.event
async def on_command_completion(ctx):
    try:
        cmd = getattr(ctx, 'command', None)
        cmd_name = getattr(cmd, 'qualified_name', None)
        if not cmd_name:
            return
        root_cmd = str(cmd_name).split()[0].lower()
        if root_cmd in AUDIT_NOISY_COMMANDS:
            return
        container = None
        node_id = None
        raw_ref = None
        for key, value in getattr(ctx, 'kwargs', {}).items():
            if value is None:
                continue
            if isinstance(value, int) and 'node' in key.lower():
                node_id = value
            elif isinstance(value, str) and ('vps' in key.lower() or 'container' in key.lower() or key.lower() in {'reference', 'container_name'}):
                raw_ref = value
        if raw_ref:
            _, _, vps = find_vps_record(raw_ref)
            if vps:
                container = str(vps.get('container_name'))
                node_id = int(vps.get('node_id', node_id or 1))
        detail = f"Executed by {getattr(ctx.author, 'display_name', ctx.author)} in {getattr(ctx.channel, 'mention', '#channel')}. Command: `{_sanitize_command_for_audit(ctx)}`"
        await record_audit_event('command', f'Command Completed • {PREFIX}{cmd_name}', detail, user_id=ctx.author.id, node_id=node_id, vps_container=container)
    except Exception:
        pass
async def bandwidth_accounting_task():
    """Persist RX+TX accounting for each running VPS with low host overhead."""
    await bot.wait_until_ready()
    await asyncio.sleep(45)
    while not bot.is_closed():
        try:
            vps_items = [v for items in list(vps_data.values()) for v in list(items) if str(v.get('status', '')).lower() == 'running' and (not v.get('suspended')) and v.get('container_name')]
            sem = asyncio.Semaphore(2)

            async def sample(vps):
                container = str(vps.get('container_name'))
                node_id = int(vps.get('node_id', 1))
                async with sem:
                    try:
                        rx, tx = await get_container_network_counters(container, node_id)
                    except Exception as exc:
                        logger.debug('Bandwidth sample failed for %s: %s', container, exc)
                        return
                now = datetime.now()
                try:
                    start_dt = datetime.fromisoformat(str(vps.get('bandwidth_cycle_start')))
                    reset = (start_dt.year, start_dt.month) != (now.year, now.month)
                except Exception:
                    reset = True
                last_rx = max(0, int(vps.get('bandwidth_last_rx_bytes') or 0))
                last_tx = max(0, int(vps.get('bandwidth_last_tx_bytes') or 0))
                last_sample = vps.get('bandwidth_last_sample_at')
                first_baseline = last_rx == 0 and last_tx == 0 and (int(vps.get('bandwidth_used_bytes') or 0) == 0)
                if first_baseline:
                    delta_rx = 0
                    delta_tx = 0
                else:
                    delta_rx = rx if rx < last_rx else rx - last_rx
                    delta_tx = tx if tx < last_tx else tx - last_tx
                used = 0 if reset else max(0, int(vps.get('bandwidth_used_bytes') or 0))
                used += delta_rx + delta_tx
                vps['bandwidth_gb'] = VPS_BANDWIDTH_GB
                vps['bandwidth_used_bytes'] = used
                vps['bandwidth_last_rx_bytes'] = rx
                vps['bandwidth_last_tx_bytes'] = tx
                vps['bandwidth_last_sample_at'] = now.isoformat()
                if reset:
                    vps['bandwidth_cycle_start'] = now.isoformat()
                with DB_LOCK:
                    conn = get_db()
                    try:
                        conn.execute('UPDATE vps SET bandwidth_gb=?, bandwidth_used_bytes=?, bandwidth_cycle_start=?, bandwidth_last_rx_bytes=?, bandwidth_last_tx_bytes=?, bandwidth_last_sample_at=?, last_modified=CURRENT_TIMESTAMP WHERE container_name=?', (VPS_BANDWIDTH_GB, used, vps.get('bandwidth_cycle_start'), rx, tx, vps.get('bandwidth_last_sample_at'), container))
                        conn.commit()
                    finally:
                        conn.close()
            for batch_start in range(0, len(vps_items), 20):
                batch = vps_items[batch_start:batch_start + 20]
                await asyncio.gather(*(sample(v) for v in batch), return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug('Bandwidth accounting task failed: %s', exc)
        await asyncio.sleep(BANDWIDTH_SAMPLE_INTERVAL)
async def audit_channel_health_task():
    """Clear a stale/deleted log-channel ID so audit logging never loops on a dead target."""
    await bot.wait_until_ready()
    await asyncio.sleep(60)
    while not bot.is_closed():
        try:
            channel_id = _audit_channel_id()
            if channel_id:
                channel = bot.get_channel(channel_id)
                if channel is None:
                    try:
                        channel = await bot.fetch_channel(channel_id)
                    except (discord.NotFound, discord.Forbidden):
                        set_audit_channel_id(0)
                        logger.warning('Configured audit log channel %s is unavailable; disabled it.', channel_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug('Audit channel health check failed: %s', exc)
        await asyncio.sleep(900)
async def node_log_health_task():
    await bot.wait_until_ready()
    await asyncio.sleep(20)
    while not bot.is_closed():
        try:
            if _audit_channel_id():
                for node in get_nodes():
                    node_id = int(node.get('id'))
                    try:
                        stats = await asyncio.wait_for(get_host_stats(node_id), timeout=12)
                        cpu = float(stats.get('cpu') or 0.0)
                        ram = float(stats.get('ram') or 0.0)
                        vps_count = sum((1 for items in vps_data.values() for v in items if int(v.get('node_id', 1)) == node_id))
                        total = int(stats.get('ram_bytes_total') or 0)
                        avail = int(stats.get('ram_bytes_available') or 0)
                        memory = f'{avail / 1024 ** 3:.1f} GiB free / {total / 1024 ** 3:.1f} GiB total' if total else 'N/A'
                        await record_audit_event('node', 'Node Health Snapshot', f'CPU `{cpu:.1f}%` • RAM `{ram:.1f}%` • {memory} • Managed VPS `{vps_count}` • Processor `{HOST_PROCESSOR_NAME}` • Provider `{HOST_PROVIDER_NAME}`.', node_id=node_id)
                    except Exception as exc:
                        await record_audit_event('error', 'Node Health Check Failed', safe_error_summary('Node health check', exc), node_id=node_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug('Node log health task failed: %s', exc)
        await asyncio.sleep(LOG_HEALTH_INTERVAL)
async def adaptive_vps_resource_scaler_task():
    """Increase live VPS RAM/CPU only when workload needs it, within pre-admitted ceilings."""
    await bot.wait_until_ready()
    await asyncio.sleep(30)
    while not bot.is_closed():
        if RESOURCE_AUTOSCALE_ENABLED:
            try:
                snapshot = [(str(uid), dict(v)) for uid, items in vps_data.items() for v in items]
            except Exception:
                snapshot = []
            for owner_id, vps in snapshot[:200]:
                if vps.get('suspended'):
                    continue
                name = str(vps.get('container_name') or '')
                node_id = int(vps.get('node_id', 1) or 1)
                if not name:
                    continue
                try:
                    stats = await asyncio.wait_for(get_container_stats(name, node_id), timeout=18)
                    if str(stats.get('status', '')).lower() != 'running':
                        continue
                    limits = stats.get('limits') or {}
                    max_ram = int(limits.get('ram_gb') or _parse_gb(vps.get('ram', '1GB'), 1))
                    max_cpu = int(limits.get('cpu') or _parse_cpu(vps.get('cpu', 1), 1))
                    current_ram = max(1, int(stats.get('ram_current_gb') or stats.get('ram', {}).get('total') or 1))
                    current_cpu = max(1, int(stats.get('cpu_current') or 1))
                    ram_pct = float(stats.get('ram', {}).get('pct') or 0.0)
                    cpu_pct = float(stats.get('cpu') or 0.0)
                    if ram_pct >= RESOURCE_SCALE_UP_RAM_THRESHOLD and current_ram < max_ram:
                        desired = min(max_ram, current_ram + 1)
                        await execute_vpsctl_compat(name, f'config set {name} limits.memory.current {desired * 1024}MB', node_id=node_id, timeout=45)
                        logger.info('Auto-scaled VPS %s RAM %s->%s GiB', name, current_ram, desired)
                    if cpu_pct >= RESOURCE_SCALE_UP_CPU_THRESHOLD and current_cpu < max_cpu:
                        desired_cpu = min(max_cpu, current_cpu + 1)
                        await execute_vpsctl_compat(name, f'config set {name} limits.cpu.current {desired_cpu}', node_id=node_id, timeout=45)
                        logger.info('Auto-scaled VPS %s CPU %s->%s', name, current_cpu, desired_cpu)
                    current_disk = max(1, int(stats.get('disk_current_gb') or _parse_gb(vps.get('storage', '10GB'), 10)))
                    max_disk = max(current_disk, int(stats.get('disk_limit_gb') or _parse_gb(vps.get('storage', '10GB'), 10)))
                    disk_pct = float(stats.get('disk_pct') or 0.0)
                    if disk_pct >= RESOURCE_SCALE_UP_DISK_THRESHOLD and current_disk < max_disk:
                        desired_disk = min(max_disk, current_disk + RESOURCE_SCALE_UP_DISK_STEP_GB)
                        await execute_vpsctl_compat(name, f'config device set {name} root size={desired_disk}GB', node_id=node_id, timeout=90)
                        grow_script = 'set +e\nROOT_DEV=$(findmnt -n -o SOURCE / 2>/dev/null || echo /dev/vda1)\nROOT_FSTYPE=$(findmnt -n -o FSTYPE / 2>/dev/null || echo ext4)\nif command -v growpart >/dev/null 2>&1; then\n  case "$ROOT_DEV" in\n    /dev/vda[0-9]*|/dev/sda[0-9]*|/dev/nvme0n1p[0-9]*)\n      BASE=$(printf \'%s\' "$ROOT_DEV" | sed -E \'s/p?[0-9]+$//\')\n      NUM=$(printf \'%s\' "$ROOT_DEV" | sed -E \'s/.*p?([0-9]+)$/\\1/\')\n      growpart "$BASE" "$NUM" >/dev/null 2>&1 || true\n      ;;\n  esac\nfi\ncase "$ROOT_FSTYPE" in\n  ext2|ext3|ext4) resize2fs "$ROOT_DEV" >/dev/null 2>&1 || true ;;\n  xfs) xfs_growfs / >/dev/null 2>&1 || true ;;\n  btrfs) btrfs filesystem resize max / >/dev/null 2>&1 || true ;;\nesac\n'
                        await _exec_guest_bash(name, node_id, grow_script, timeout=90)
                        logger.info('Auto-expanded VPS %s disk %s->%s GiB (%.1f%% used)', name, current_disk, desired_disk, disk_pct)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug('Adaptive resource scaler skipped %s: %s', name, exc)
        await asyncio.sleep(RESOURCE_AUTOSCALE_INTERVAL)
def _load_threshold_setting(key: str, env_name: str, default: int=90) -> int:
    fallback = env_int(env_name, default)
    try:
        raw = get_setting(key, os.getenv(env_name, str(default)))
        value = int(str(raw).strip())
    except (TypeError, ValueError, sqlite3.Error):
        logger.warning('Invalid persisted resource threshold %r; using environment/default value', key)
        value = fallback
    return max(0, min(100, value))
class AXIONHOSTMaintenanceError(commands.CheckFailure):
    """Raised when a normal-user command is blocked by maintenance mode."""
class AXIONHOSTView(discord.ui.View):
    """Base view with a safe Discord UI error response."""

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        error_id = secrets.token_hex(4).upper()
        logger.error('Discord UI callback failed [%s] item=%s: %s', error_id, getattr(item, 'custom_id', None) or getattr(item, 'label', type(item).__name__), error, exc_info=True)
        message = 'The requested action could not be completed right now. No destructive operation was continued. Please try again.'
        if is_admin_user(getattr(interaction, 'user', None)):
            message += f'\n\n**Error ID:** `{error_id}`\n**Error type:** `{type(error).__name__}`'
        else:
            message += f'\n\n**Error ID:** `{error_id}`'
        try:
            embed = create_error_embed('⚠️ Action Failed', message)
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception:
            logger.exception('Unable to deliver UI error response [%s]', error_id)
async def _publish_log_bundle(channel, embed, content: str, filename: str) -> None:
    """Publish an operational log embed plus a bounded text attachment.

    Discord embeds are intentionally small; the attachment preserves a useful
    complete snapshot without flooding the channel with many messages.
    """
    if channel is None or not hasattr(channel, 'send'):
        return
    content = str(content or 'No log output.')
    content = content[-90000:]
    payload = io.BytesIO(content.encode('utf-8', errors='replace'))
    file = discord.File(payload, filename=str(filename)[:80])
    await channel.send(embed=embed, file=file, allowed_mentions=discord.AllowedMentions.none())
def _audit_channel_id() -> int:
    try:
        return int(get_setting('logs_channel_id', '0') or 0)
    except (TypeError, ValueError):
        return 0
def set_audit_channel_id(channel_id: Optional[int]) -> None:
    set_setting('logs_channel_id', str(int(channel_id or 0)))
def get_motd_text() -> str:
    return str(get_setting('motd_text', DEFAULT_MOTD_TEXT) or '').replace('\\n', '\n').strip()[:1200]
async def record_audit_event(kind: str, action: str, detail: str='', user_id: Optional[int | str]=None, node_id: Optional[int]=None, vps_container: Optional[str]=None, announce: bool=True) -> None:
    safe_detail = str(detail or '').strip()[:1800]
    safe_kind = str(kind or 'system').strip()[:32]
    safe_action = str(action or 'event').strip()[:120]
    try:
        with DB_LOCK:
            conn = get_db()
            try:
                conn.execute('INSERT INTO audit_logs (kind, action, detail, user_id, node_id, vps_container, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)', (safe_kind, safe_action, safe_detail, str(user_id) if user_id is not None else None, int(node_id) if node_id is not None else None, str(vps_container)[:120] if vps_container else None, datetime.now().isoformat()))
                conn.execute('DELETE FROM audit_logs WHERE id NOT IN (SELECT id FROM audit_logs ORDER BY id DESC LIMIT 2000)')
                conn.commit()
            finally:
                conn.close()
    except Exception as exc:
        logger.warning('Audit log persistence failed: %s', exc)
        return
    if not announce:
        return
    channel_id = _audit_channel_id()
    if not channel_id:
        return
    try:
        channel = bot.get_channel(channel_id)
        if channel is None:
            channel = await bot.fetch_channel(channel_id)
        if not hasattr(channel, 'send'):
            return
        icon = {'vps': '🖥️', 'node': '🧩', 'command': '⌘', 'system': '⚙️', 'security': '🛡️', 'error': '🚨'}.get(safe_kind, '📝')
        embed = create_info_embed(f'{icon} {safe_action}', safe_detail or 'No additional details.')
        if node_id is not None:
            add_field(embed, 'Node', f'`{node_id}`', True)
        if vps_container:
            add_field(embed, 'VPS', f'`{vps_container}`', True)
        if user_id is not None:
            add_field(embed, 'User', f'`{user_id}`', True)
        embed.set_footer(text=f'{HOST_PROVIDER_NAME} • AxionHost audit log')
        async with AUDIT_CHANNEL_SEND_LOCK:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except Exception as exc:
        logger.debug('Could not publish audit log to channel %s: %s', channel_id, exc)
def get_recent_audit_logs(limit: int=20, *, vps_container: Optional[str]=None, node_id: Optional[int]=None) -> list[dict]:
    limit = max(1, min(100, int(limit)))
    clauses = []
    params: list = []
    if vps_container:
        clauses.append('vps_container = ?')
        params.append(str(vps_container))
    if node_id is not None:
        clauses.append('node_id = ?')
        params.append(int(node_id))
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    params.append(limit)
    with DB_LOCK:
        conn = get_db()
        try:
            rows = conn.execute(f'SELECT kind, action, detail, user_id, node_id, vps_container, created_at FROM audit_logs{where} ORDER BY id DESC LIMIT ?', params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
def _safe_fromiso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.max
def _parse_gb(value: Any, default: int) -> int:
    try:
        return max(1, int(float(str(value).strip().lower().replace('gb', '').strip())))
    except (TypeError, ValueError):
        return int(default)
def _parse_cpu(value: Any, default: int) -> int:
    try:
        return max(1, int(float(str(value).strip())))
    except (TypeError, ValueError):
        return int(default)
async def status_presence_task():
    while not bot.is_closed():
        try:
            created, total_slots, running, expired = get_presence_counts()
            if maintenance_enabled():
                activity = f'🔧 MAINTENANCE | {created}/{total_slots} VPS | 🟢 {running} Running'
            else:
                activity = f'🖥️ {created}/{total_slots} | 🟢 {running} Running | ⏰ {expired} Expired'
            await bot.change_presence(activity=discord.Game(name=activity))
        except Exception as e:
            logger.debug(f'Presence update failed: {e}')
        await asyncio.sleep(30)
def build_rgnodes_motd_profile_script(motd_text: str) -> str:
    """Build a POSIX-shell login banner without touching PAM, sshd, or system MOTD hooks."""
    custom_b64 = base64.b64encode(str(motd_text or '').replace('\x00', '').strip()[:1200].encode('utf-8')).decode('ascii')
    template = '#!/bin/sh\n# AxionHost MOTD installer (safe embedded adaptation of the requested installer).\n# This file is sourced by /etc/profile. It never edits PAM/sshd or disables distro MOTD hooks.\ncase "$-" in *i*) ;; *) return 0 2>/dev/null || exit 0 ;; esac\n[ -t 1 ] || return 0 2>/dev/null || exit 0\nif [ -z "${SSH_CONNECTION:-}${SSH_TTY:-}" ]; then return 0 2>/dev/null || exit 0; fi\n[ "${AXIONHOST_MOTD_SHOWN:-0}" = 1 ] && return 0 2>/dev/null || :\nAXIONHOST_MOTD_SHOWN=1\nexport AXIONHOST_MOTD_SHOWN\n\nGREEN=$(printf \'\\033[38;5;82m\')\nCYAN=$(printf \'\\033[38;5;51m\')\nBLUE=$(printf \'\\033[38;5;39m\')\nMAGENTA=$(printf \'\\033[38;5;213m\')\nYELLOW=$(printf \'\\033[38;5;220m\')\nGRAY=$(printf \'\\033[38;5;245m\')\nRESET=$(printf \'\\033[0m\')\n\nHOSTNAME_VALUE=$(hostname 2>/dev/null || uname -n 2>/dev/null || printf \'unknown\')\nOS_VALUE=$(sed -n \'s/^PRETTY_NAME=//p\' /etc/os-release 2>/dev/null | head -n 1 | sed \'s/^"//;s/"$//\')\n[ -n "$OS_VALUE" ] || OS_VALUE=$(uname -s 2>/dev/null || printf \'Linux\')\nKERNEL_VALUE=$(uname -r 2>/dev/null || printf \'N/A\')\nUPTIME_VALUE=$(uptime -p 2>/dev/null | sed \'s/^up //\' || true)\n[ -n "$UPTIME_VALUE" ] || UPTIME_VALUE=$(uptime 2>/dev/null | sed \'s/^[^,]*up /up /\' | cut -c1-80 || printf \'N/A\')\n\ncpu_usage() {\n    [ -r /proc/stat ] || { printf \'N/A\'; return; }\n    set -- $(awk \'NR==1 {t=$2+$3+$4+$5+$6+$7+$8+$9; i=$5+$6; printf "%.0f %.0f",t,i}\' /proc/stat 2>/dev/null)\n    t1=${1:-0}; i1=${2:-0}\n    sleep 0.1 2>/dev/null || true\n    set -- $(awk \'NR==1 {t=$2+$3+$4+$5+$6+$7+$8+$9; i=$5+$6; printf "%.0f %.0f",t,i}\' /proc/stat 2>/dev/null)\n    t2=${1:-0}; i2=${2:-0}\n    dt=$((t2-t1)); di=$((i2-i1))\n    if [ "$dt" -gt 0 ] 2>/dev/null; then\n        pct=$(((dt-di)*100/dt)); [ "$pct" -lt 0 ] && pct=0; [ "$pct" -gt 100 ] && pct=100\n        printf \'%s%%\' "$pct"\n    else printf \'N/A\'; fi\n}\nCPU_VALUE=$(cpu_usage 2>/dev/null || printf \'N/A\')\nMEM_VALUE=$(awk \'/^MemTotal:/ {t=$2} /^MemAvailable:/ {a=$2} END {if (t>0) {u=t-a; if(u<0)u=0; printf "%d/%d MB (%d%%)",u/1024,t/1024,u*100/t} else print "N/A"}\' /proc/meminfo 2>/dev/null)\n[ -n "$MEM_VALUE" ] || MEM_VALUE=\'N/A\'\nDISK_VALUE=$(df -h / 2>/dev/null | awk \'NR==2 {printf "%s / %s (%s)",$3,$2,$5}\')\n[ -n "$DISK_VALUE" ] || DISK_VALUE=\'N/A\'\nIP_VALUE=$(hostname -I 2>/dev/null | awk \'{$1=$1; print $1}\')\n[ -n "$IP_VALUE" ] || IP_VALUE=$(ip -4 -o addr show scope global 2>/dev/null | awk \'NR==1 {split($4,a,"/"); print a[1]}\')\n[ -n "$IP_VALUE" ] || IP_VALUE=\'N/A\'\nUSER_COUNT=$(who 2>/dev/null | wc -l | tr -d \' \')\nPROC_COUNT=$(ps -e 2>/dev/null | wc -l | awk \'{print ($1>0 ? $1-1 : 0)}\')\n\nprintf \'\\n%s\' "$MAGENTA"\nprintf \'%s\\n\' \'██████╗  ██████╗ ███╗   ██╗ ██████╗ ██████╗ ███████╗███████╗™\'\nprintf \'%s\\n\' \'██╔══██╗██╔════╝ ████╗  ██║██╔══██╗██╔══██╗██╔════╝██╔════╝\'\nprintf \'%s\\n\' \'██████╔╝██║  ██╗ ██╔██╗ ██║██║  ██║██║  ██║█████╗  ╚█████╗ \'\nprintf \'%s\\n\' \'██╔══██╗██║  ╚██╗██║╚██╗██║██║  ██║██║  ██║██╔══╝  ╚═══██╗ \'\nprintf \'%s\\n\' \'██║  ██║╚██████╔╝██║ ╚████║╚█████╔╝██████╔╝███████╗██████╔╝\'\nprintf \'%s\\n\' \'╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚══╝ ╚════╝ ╚═════╝ ╚══════╝╚═════╝  \'\nprintf \'%s\\n\' "$RESET"\nprintf \'%s\\n\' "${GREEN}🚀 Welcome to AxionHost Datacenter${RESET}"\nprintf \'%s\\n\' "${BLUE}High Performance • Secure • Reliable Infrastructure${RESET}"\nprintf \'%s\\n\' "${GRAY}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"\nprintf \'%s%-18s%s %s\\n\' "$CYAN" \'Hostname:\' "$RESET" "$HOSTNAME_VALUE"\nprintf \'%s%-18s%s %s\\n\' "$CYAN" \'OS:\' "$RESET" "$OS_VALUE"\nprintf \'%s%-18s%s %s\\n\' "$CYAN" \'Kernel:\' "$RESET" "$KERNEL_VALUE"\nprintf \'%s%-18s%s %s\\n\' "$CYAN" \'Uptime:\' "$RESET" "$UPTIME_VALUE"\nprintf \'%s%-18s%s %s\\n\' "$CYAN" \'CPU Usage:\' "$RESET" "$CPU_VALUE"\nprintf \'%s%-18s%s %s\\n\' "$CYAN" \'Memory:\' "$RESET" "$MEM_VALUE"\nprintf \'%s%-18s%s %s\\n\' "$CYAN" \'Disk:\' "$RESET" "$DISK_VALUE"\nprintf \'%s%-18s%s %s\\n\' "$CYAN" \'Processes:\' "$RESET" "$PROC_COUNT"\nprintf \'%s%-18s%s %s\\n\' "$CYAN" \'Users:\' "$RESET" "$USER_COUNT"\nprintf \'%s%-18s%s %s\\n\' "$CYAN" \'IP:\' "$RESET" "$IP_VALUE"\nprintf \'%s\\n\' "${GRAY}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"\nCUSTOM_MOTD_B64=\'@@CUSTOM_MOTD_B64@@\'\nif command -v base64 >/dev/null 2>&1 && [ -n "$CUSTOM_MOTD_B64" ]; then\n    CUSTOM_MOTD=$(printf \'%s\' "$CUSTOM_MOTD_B64" | base64 -d 2>/dev/null || true)\n    if [ -n "$CUSTOM_MOTD" ]; then printf \'%s\\n\' "$CUSTOM_MOTD"; fi\nfi\nprintf \'%s\\n\' "${GREEN}Support:${RESET}  support@rgnodes.cloud"\nprintf \'%s\\n\' "${GREEN}Discord:${RESET}  https://discord.gg/wJ5D5MHkUA"\nprintf \'%s\\n\' "${GREEN}Website:${RESET}  https://www.rgnodes.qzz.io/"\nprintf \'%s\\n\\n\' "${MAGENTA}AxionHost — Free Hosting 💎${RESET}"\n'
    return template.replace('@@CUSTOM_MOTD_B64@@', custom_b64)
async def apply_guest_motd(container_name: str, node_id: int, motd_text: Optional[str]=None) -> bool:
    """Install the safe AXIONHOST login MOTD, preserving PAM/sshd and distro hooks.

    The upstream installer currently edits PAM, disables distro update-motd hooks and
    deletes /etc/motd. The embedded equivalent provides the same branded system summary
    without executing mutable remote code or altering authentication configuration.
    """
    text = str(motd_text if motd_text is not None else get_motd_text() or '').replace('\x00', '').strip()[:1200]
    try:
        if not text:
            remote = "rm -f -- /etc/profile.d/00-rgnodes-motd.sh /etc/profile.d/99-rgnodes-motd.sh; printf 'MOTD_CLEARED\\n'"
            out = await _exec_guest_bash(container_name, node_id, remote, timeout=30)
            return 'MOTD_CLEARED' in str(out or '')
        if AUTO_MOTD_INSTALLER:
            installer = build_rgnodes_motd_profile_script(text)
            encoded_script = base64.b64encode(installer.encode('utf-8')).decode('ascii')
            profile_path = '/etc/profile.d/99-rgnodes-motd.sh'
            remote = f"""set -Eeuo pipefail\ncommand -v base64 >/dev/null 2>&1 || {{ echo 'MOTD install failed: base64 is required' >&2; exit 20; }}\ninstall -d -m 0755 /etc/profile.d\numask 022\ntmp="$(mktemp /etc/profile.d/.99-rgnodes-motd.sh.XXXXXX)"\ntrap 'rm -f -- "$tmp"' EXIT\nprintf '%s' '{encoded_script}' | base64 -d > "$tmp"\nsh -n "$tmp"\nchmod 0644 "$tmp"\nif [ -f {shlex.quote(profile_path)} ] && cmp -s "$tmp" {shlex.quote(profile_path)}; then\n  rm -f -- "$tmp"\nelse\n  mv -f -- "$tmp" {shlex.quote(profile_path)}\nfi\n# Clean only the bot's legacy profile hook to avoid duplicate banners.\nrm -f -- /etc/profile.d/00-rgnodes-motd.sh\ntrap - EXIT\nprintf 'AXIONHOST_MOTD_INSTALLED_SAFE\\n'\n"""
            out = await _exec_guest_bash(container_name, node_id, remote, timeout=45)
            return 'AXIONHOST_MOTD_INSTALLED_SAFE' in str(out or '')
        b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
        profile_path = '/etc/profile.d/00-rgnodes-motd.sh'
        remote = f"""set -Eeuo pipefail\ninstall -d -m 0755 /etc/profile.d\nprintf '%s' '{b64}' | base64 -d > /etc/motd\nchmod 0644 /etc/motd\nrm -f -- /etc/profile.d/99-rgnodes-motd.sh\nif grep -RqsE '^[[:space:]]*[^#].*pam_motd\\.so' /etc/pam.d 2>/dev/null; then\n  rm -f -- {shlex.quote(profile_path)}\n  printf 'MOTD_READY_PAM\\n'\nelse\n  cat > {shlex.quote(profile_path)} <<'AXIONHOST_MOTD_EOF'\n#!/bin/sh\ncase "$-" in *i*) ;; *) return 0 2>/dev/null || exit 0 ;; esac\nif [ -n "${{SSH_CONNECTION:-}}${{SSH_TTY:-}}" ] && [ -t 1 ] && [ -r /etc/motd ]; then cat /etc/motd; fi\nAXIONHOST_MOTD_EOF\n  chmod 0644 {shlex.quote(profile_path)}\n  printf 'MOTD_READY_PROFILE\\n'\nfi\n"""
        out = await _exec_guest_bash(container_name, node_id, remote, timeout=45)
        out_text = str(out or '')
        return 'MOTD_READY_PAM' in out_text or 'MOTD_READY_PROFILE' in out_text
    except Exception as exc:
        logger.warning('MOTD apply failed for %s: %s', container_name, exc)
        return False
async def apply_motd_to_all_running_vps() -> tuple[int, int]:
    ok = failed = 0
    sem = asyncio.Semaphore(2)

    async def one(vps):
        nonlocal ok, failed
        if str(vps.get('status', '')).lower() != 'running' or vps.get('suspended'):
            return
        async with sem:
            try:
                if await apply_guest_motd(str(vps.get('container_name')), int(vps.get('node_id', 1))):
                    ok += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
    items = [v for owner_items in list(vps_data.values()) for v in list(owner_items)]
    for start in range(0, len(items), 20):
        await asyncio.gather(*(one(v) for v in items[start:start + 20]), return_exceptions=True)
    return (ok, failed)
async def set_guest_hostname(container_name: str, node_id: int, hostname: str=VPS_HOSTNAME):
    safe = re.sub('[^A-Za-z0-9.-]', '-', hostname).strip('.-') or 'rgnodes-vps'
    script = f"set -e\nprintf '%s\\n' {shlex.quote(safe)} > /etc/hostname\n(hostnamectl set-hostname {shlex.quote(safe)} 2>/dev/null || hostname {shlex.quote(safe)} || true)\nsed -i -E '/^[[:space:]]*127\\.0\\.1\\.1[[:space:]]+/d' /etc/hosts 2>/dev/null || true\nprintf '127.0.1.1 %s\\n' {shlex.quote(safe)} >> /etc/hosts\n"
    return await _exec_guest_bash(container_name, node_id, script, timeout=60)
async def bootstrap_vps_guest(container_name: str, node_id: int):
    """Install the lightweight AXIONHOST baseline; heavy virtualization is never installed automatically."""
    script = "set -Eeuo pipefail\nexport DEBIAN_FRONTEND=noninteractive\nexport NEEDRESTART_MODE=a\nif command -v apt-get >/dev/null 2>&1; then\n  for attempt in 1 2 3 4; do apt-get update -qq && break; sleep $((attempt*2)); done\n  apt-get install -y --no-install-recommends bash coreutils grep sed gawk sudo openssh-server openssh-client curl ca-certificates iproute2 iputils-ping procps net-tools python3 python3-pip\nelif command -v dnf >/dev/null 2>&1; then\n  dnf install -y bash coreutils grep sed gawk sudo openssh-server openssh-clients curl ca-certificates iproute iputils procps-ng net-tools python3 python3-pip\nelif command -v yum >/dev/null 2>&1; then\n  yum install -y bash coreutils grep sed gawk sudo openssh-server openssh-clients curl ca-certificates iproute iputils procps net-tools python3 python3-pip\nelif command -v apk >/dev/null 2>&1; then\n  apk add --no-cache bash coreutils grep sed gawk sudo openssh curl ca-certificates iproute2 iputils procps net-tools python3 py3-pip\nelse\n  echo 'SUPPORTED_PACKAGE_MANAGER_NOT_FOUND' >&2\n  exit 20\nfi\nmkdir -p /etc/ssh/sshd_config.d /run/sshd /var/lib/rgnodes\ncommand -v sshd >/dev/null 2>&1 || { echo 'SSH_SERVER_MISSING' >&2; exit 21; }\nprintf 'BASELINE_READY\\n'\n"
    await _exec_guest_bash(container_name, node_id, script, timeout=GUEST_BOOTSTRAP_TIMEOUT)
async def install_anti_mining_guard(container_name: str, node_id: int):
    """Install conservative best-effort anti-cryptomining protection in every VPS."""
    if not ANTI_MINING_ENABLED:
        return
    script = 'set +u\ncat > /usr/local/sbin/rgnodes-mining-guard <<\'GUARD\'\n#!/usr/bin/env bash\nset +e\nMINER_NAMES=\'^(xmrig|xmrig-proxy|xmr-stak|cpuminer|cpuminer-multi|minerd|ccminer|cgminer|bfgminer|nbminer|lolminer|t-rex|ethminer|nanominer|rigel|gminer|teamredminer|phoenixminer)$\'\nfor proc in /proc/[0-9]*; do\n  pid=${proc##*/}\n  [ "$pid" = "$$" ] && continue\n  [ -r "$proc/cmdline" ] || continue\n  [ -r "$proc/comm" ] || continue\n  comm=$(tr -d \'\\0\\n\' < "$proc/comm" 2>/dev/null)\n  cmd=$(tr \'\\0\' \' \' < "$proc/cmdline" 2>/dev/null)\n  lower_comm=$(printf \'%s\' "$comm" | tr \'[:upper:]\' \'[:lower:]\')\n  lower_cmd=$(printf \'%s\' "$cmd" | tr \'[:upper:]\' \'[:lower:]\')\n  suspicious=0\n  printf \'%s\\n\' "$lower_comm" | grep -Eq "$MINER_NAMES" && suspicious=1\n  printf \'%s\\n\' "$lower_cmd" | grep -Eq \'(^|[[:space:]])(stratum\\+tcp|stratum\\+ssl|ethashstratum|nicehash)([^[:alnum:]_-]|$)\' && suspicious=1\n  [ "$suspicious" -eq 1 ] || continue\n  case "$lower_cmd" in\n    *rgnodes-mining-guard*|*/sshd*|*/systemd*|*/init*|*cloud-init*|*apt*|*dpkg*) continue ;;\n  esac\n  kill -TERM "$pid" 2>/dev/null || true\n  sleep 0.25\n  kill -KILL "$pid" 2>/dev/null || true\n  logger -t rgnodes-mining-guard "Blocked suspected cryptominer pid=$pid comm=$comm" 2>/dev/null || true\ndone\nGUARD\nchmod 0755 /usr/local/sbin/rgnodes-mining-guard\nif command -v systemctl >/dev/null 2>&1; then\n  cat > /etc/systemd/system/rgnodes-mining-guard.service <<\'EOF2\'\n[Unit]\nDescription=AXIONHOST Anti-Mining Protection\nAfter=multi-user.target\n\n[Service]\nType=oneshot\nExecStart=/usr/local/sbin/rgnodes-mining-guard\nEOF2\n  cat > /etc/systemd/system/rgnodes-mining-guard.timer <<\'EOF2\'\n[Unit]\nDescription=AXIONHOST Anti-Mining Protection Timer\n\n[Timer]\nOnBootSec=30s\nOnUnitActiveSec=30s\nAccuracySec=5s\nPersistent=true\nUnit=rgnodes-mining-guard.service\n\n[Install]\nWantedBy=timers.target\nEOF2\n  systemctl daemon-reload >/dev/null 2>&1 || true\n  systemctl enable --now rgnodes-mining-guard.timer >/dev/null 2>&1 || true\nelse\n  mkdir -p /etc/cron.d\n  printf \'*/1 * * * * root /usr/local/sbin/rgnodes-mining-guard >/dev/null 2>&1\\n\' > /etc/cron.d/rgnodes-mining-guard\n  chmod 0644 /etc/cron.d/rgnodes-mining-guard\nfi\n/usr/local/sbin/rgnodes-mining-guard >/dev/null 2>&1 || true\n'
    try:
        await _exec_guest_bash(container_name, node_id, script, timeout=45)
    except Exception as e:
        logger.warning(f'Anti-mining guard installation skipped for {container_name}: {e}')
async def _run_tunnel_control(container_name: str, node_id: int, action: str, tunnel_name: str, timeout: int=60):
    """Start/restart exactly one tunnel supervisor.

    Some VPS cloud images provide a `systemctl` client even when systemd is not PID 1, so the
    real init process is detected before systemd is used. Non-systemd guests get
    a direct supervisor plus a cron @reboot fallback.
    """
    if action not in {'start', 'restart'}:
        raise ValueError('Unsupported tunnel control action')
    if tunnel_name != 'pinggy':
        raise ValueError('Unsupported tunnel name')
    sup = f'/usr/local/sbin/rgnodes-{tunnel_name}-supervisor'
    service = f'rgnodes-{tunnel_name}.service'
    log = f'/var/lib/rgnodes/{tunnel_name}-supervisor.log'
    supervisor_pid_file = f'/var/lib/rgnodes/{tunnel_name}.supervisor.pid'
    cron_file = f'/etc/cron.d/rgnodes-{tunnel_name}'
    command = 'set +e\nsystemd_ok=false\n[ -d /run/systemd/system ] && [ "$(cat /proc/1/comm 2>/dev/null)" = "systemd" ] && systemd_ok=true\nSUP="__SUP__"\nSERVICE="__SERVICE__"\nLOG="__LOG__"\nSUPPID="__SUPPID__"\nCRON_FILE="__CRON_FILE__"\nis_alive() {\n  pid=$(cat "$SUPPID" 2>/dev/null | head -n1)\n  [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1\n}\nstart_bg() {\n  is_alive && return 0\n  mkdir -p "$(dirname "$LOG")"\n  nohup "$SUP" >>"$LOG" 2>&1 </dev/null &\n  sleep 1\n}\nstop_bg() {\n  pid=$(cat "$SUPPID" 2>/dev/null | head -n1)\n  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then\n    kill -TERM "$pid" >/dev/null 2>&1 || true\n    for _ in 1 2 3 4 5; do\n      sleep 1\n      kill -0 "$pid" >/dev/null 2>&1 || break\n    done\n    kill -KILL "$pid" >/dev/null 2>&1 || true\n  fi\n  rm -f "$SUPPID"\n}\nif [ "$systemd_ok" = true ]; then\n  systemctl daemon-reload >/dev/null 2>&1 || true\n  if [ "__ACTION__" = "restart" ]; then\n    systemctl --no-block restart "$SERVICE" >/dev/null 2>&1 || true\n  else\n    systemctl --no-block start "$SERVICE" >/dev/null 2>&1 || true\n  fi\n  systemctl enable "$SERVICE" >/dev/null 2>&1 || true\nelse\n  stop_bg\n  start_bg\nfi\nif [ "$systemd_ok" = true ] && ! systemctl is-active --quiet "$SERVICE" >/dev/null 2>&1; then\n  start_bg\nfi\nif [ "$systemd_ok" != true ]; then\n  start_bg\n  mkdir -p /etc/cron.d\n  printf \'SHELL=/bin/sh\\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\\n@reboot root %s >>%s 2>&1\\n\' "$SUP" "$LOG" > "$CRON_FILE"\n  chmod 0644 "$CRON_FILE" 2>/dev/null || true\n  if command -v service >/dev/null 2>&1; then\n    service cron start >/dev/null 2>&1 || service crond start >/dev/null 2>&1 || true\n  elif command -v cron >/dev/null 2>&1; then\n    pgrep -x cron >/dev/null 2>&1 || nohup cron >/dev/null 2>&1 &\n  elif command -v crond >/dev/null 2>&1; then\n    pgrep -x crond >/dev/null 2>&1 || nohup crond >/dev/null 2>&1 &\n  fi\nfi\nif is_alive; then\n  printf \'TUNNEL_CONTROL_DONE\\n\'\nelse\n  printf \'TUNNEL_CONTROL_FAILED\\n\'\nfi\n'.replace('__ACTION__', action).replace('__SUP__', sup).replace('__SERVICE__', service).replace('__LOG__', log).replace('__CRON_FILE__', cron_file).replace('__SUPPID__', supervisor_pid_file)
    return await _exec_guest_bash(container_name, node_id, command, timeout=timeout)
def _get_deploy_node_lock(node_id: int) -> asyncio.Lock:
    key = int(node_id)
    lock = DEPLOY_NODE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        DEPLOY_NODE_LOCKS[key] = lock
    return lock
def parse_pinggy_endpoint(output: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Parse Pinggy's published TCP endpoint, including multi-label hostnames."""
    cleaned = ANSI_RE.sub('', str(output or '')).replace("\r", "\n")
    pattern = re.compile(
        r"(?:tcp://)?([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+):(\d{2,5})(?!\d)",
        re.I,
    )
    for match in pattern.finditer(cleaned):
        host = match.group(1).rstrip('.,;:)]}').lower()
        try:
            port = int(match.group(2))
        except (TypeError, ValueError):
            continue
        if host == 'free.pinggy.io' or host.endswith('.free.pinggy.io'):
            continue
        if 1 <= port <= 65535:
            return host, port, f"tcp://{host}:{port}"
    return None, None, None

async def _install_tunnel_supervisors_unlocked(container_name: str, node_id: int) -> None:
    """Install the lightweight Pinggy supervisor (serialized wrapper below)."""
    safe_host = re.sub('[^A-Za-z0-9.-]', '', PINGGY_HOST).strip('.') or 'free.pinggy.io'
    safe_port = max(1, min(65535, int(PINGGY_SSH_PORT)))
    safe_remote_port = max(0, min(65535, int(PINGGY_REMOTE_PORT)))
    script = r'''set +e
export DEBIAN_FRONTEND=noninteractive
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
D=/var/lib/rgnodes
mkdir -p /usr/local/sbin "$D"

install_pkg() {
  pkgs="$*"
  [ -n "$pkgs" ] || return 0
  if command -v apt-get >/dev/null 2>&1; then
    # Avoid repeated apt index downloads on every tunnel health check.
    apt-get install -y --no-install-recommends $pkgs >/dev/null 2>&1 || {
      apt-get update -qq >/dev/null 2>&1 || true
      apt-get install -y --no-install-recommends $pkgs >/dev/null 2>&1 || true
    }
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache $pkgs >/dev/null 2>&1 || true
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y $pkgs >/dev/null 2>&1 || true
  elif command -v yum >/dev/null 2>&1; then
    yum install -y $pkgs >/dev/null 2>&1 || true
  elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive install -y $pkgs >/dev/null 2>&1 || true
  fi
}
command -v ssh >/dev/null 2>&1 || install_pkg openssh-client
command -v ssh >/dev/null 2>&1 || install_pkg openssh-clients
command -v curl >/dev/null 2>&1 || install_pkg curl
command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 || install_pkg wget
command -v script >/dev/null 2>&1 || install_pkg util-linux
command -v flock >/dev/null 2>&1 || true


cat > /usr/local/sbin/rgnodes-pinggy-supervisor <<'EOF_PINGGY'
#!/usr/bin/env bash
set +e
D=/var/lib/rgnodes
LOG="$D/pinggy.log"
INFO="$D/pinggy.info"
PID="$D/pinggy.pid"
SUPPID="$D/pinggy.supervisor.pid"
KEY="$D/pinggy_ed25519"
HOST="__PINGGY_HOST__"
PORT="__PINGGY_PORT__"
REMOTE_PORT="__PINGGY_REMOTE_PORT__"
LOCK="$D/pinggy.lock"
mkdir -p "$D"
printf '%s\n' "$$" > "$SUPPID"
exec 8>"$LOCK"
if command -v flock >/dev/null 2>&1; then flock -n 8 || exit 0; fi
extract_endpoint() {
  cleaned=$(sed -E $'s/\x1B\[[0-9;]*[[:alpha:]]//g' "$LOG" 2>/dev/null || true)
  endpoint=$(printf '%s\n' "$cleaned" | grep -Eo '[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9-]{2,}(\.[A-Za-z0-9-]{2,})+:[0-9]{2,5}' | grep -vE 'free\.pinggy\.io:' | head -n1 || true)
  if [ -z "$endpoint" ]; then
    endpoint=$(printf '%s\n' "$cleaned" | grep -Eo 'tcp://[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9-]{2,}(\.[A-Za-z0-9-]{2,})+:[0-9]{2,5}' | grep -vE 'free\.pinggy\.io:' | head -n1 || true)
  fi
  if [ -z "$endpoint" ]; then
    endpoint=$(printf '%s\n' "$cleaned" | grep -Eo '[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9-]{2,}(\.[A-Za-z0-9-]{2,})+:[0-9]{2,5}' | grep -vE '^free\.pinggy\.io:' | head -n1 || true)
  fi
  printf '%s\n' "$endpoint"
}
child=''
cleanup() {
  if [ -n "$child" ]; then
    kill "$child" >/dev/null 2>&1 || true
    wait "$child" >/dev/null 2>&1 || true
  fi
  rm -f "$PID" "$SUPPID"
}
trap cleanup EXIT
trap 'exit 0' INT TERM
while true; do
  if [ -f "$LOG" ] && [ "$(wc -c < "$LOG" 2>/dev/null || echo 0)" -gt 2097152 ]; then
    tail -c 524288 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG" 2>/dev/null || true
  fi
  : > "$INFO"
  connected=0
  # If the account allows a reserved port, request it first. Free Pinggy commonly assigns
  # a random public port, so retry with port 0 if the fixed request is rejected.
  for requested_port in "$REMOTE_PORT" 0; do
    if [ "$requested_port" = "0" ]; then forward="0:127.0.0.1:22"; else forward="$requested_port:127.0.0.1:22"; fi
    : > "$LOG"
    (printf '\n' | ssh -T \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o UpdateHostkeys=no \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -o TCPKeepAlive=yes \
        -o ExitOnForwardFailure=yes \
        -o ConnectTimeout=15 \
        -o ConnectionAttempts=2 \
        -o PreferredAuthentications=keyboard-interactive,password \
        -o PubkeyAuthentication=no \
        -o PasswordAuthentication=yes \
        -o KbdInteractiveAuthentication=yes \
        -p "$PORT" -R "$forward" "tcp@$HOST" >"$LOG" 2>&1) &
    child=$!
    printf '%s\n' "$child" > "$PID"
    for _ in $(seq 1 30); do
      sleep 1
      endpoint=$(extract_endpoint)
      if [ -n "$endpoint" ]; then
        case "$endpoint" in tcp://*) ;; *) endpoint="tcp://$endpoint" ;; esac
        printf '%s\n' "$endpoint" > "$INFO"
        connected=1
        break
      fi
      kill -0 "$child" >/dev/null 2>&1 || break
    done
    if [ "$connected" -eq 1 ]; then
      wait "$child" >/dev/null 2>&1 || true
      break
    fi
    kill "$child" >/dev/null 2>&1 || true
    wait "$child" >/dev/null 2>&1 || true
    rm -f "$PID"
    [ "$requested_port" = "0" ] && break
  done
  rm -f "$PID"
  sleep 4
done
EOF_PINGGY
chmod 0755 /usr/local/sbin/rgnodes-pinggy-supervisor

if [ -d /run/systemd/system ] && [ "$(cat /proc/1/comm 2>/dev/null)" = "systemd" ]; then
  cat > /etc/systemd/system/rgnodes-pinggy.service <<'EOF_UNIT'
[Unit]
Description=AXIONHOST Pinggy SSH Tunnel Supervisor
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=/usr/local/sbin/rgnodes-pinggy-supervisor
Restart=always
RestartSec=3
KillMode=control-group
[Install]
WantedBy=multi-user.target
EOF_UNIT
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl enable rgnodes-pinggy.service >/dev/null 2>&1 || true
else
  mkdir -p /etc/cron.d
  printf '%s\n' '@reboot root /usr/local/sbin/rgnodes-pinggy-supervisor >>/var/lib/rgnodes/pinggy-supervisor.log 2>&1' > /etc/cron.d/rgnodes-pinggy
  chmod 0644 /etc/cron.d/rgnodes-pinggy 2>/dev/null || true
fi
printf 'TUNNEL_SUPERVISORS_READY\n'
'''.replace('__PINGGY_HOST__', safe_host).replace('__PINGGY_PORT__', str(safe_port)).replace('__PINGGY_REMOTE_PORT__', str(safe_remote_port))
    await _exec_guest_bash(container_name, node_id, script, timeout=180)
async def install_tunnel_supervisors(container_name: str, node_id: int) -> None:
    """Serialize tunnel bootstrap per VPS to avoid package-manager/systemd races."""
    key = (str(container_name), int(node_id))
    lock = TUNNEL_SETUP_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        TUNNEL_SETUP_LOCKS[key] = lock
    async with lock:
        await _install_tunnel_supervisors_unlocked(container_name, node_id)
async def start_pinggy_session(container_name: str, node_id: int) -> Optional[dict]:
    """Restart Pinggy's durable supervisor and return the fresh public TCP endpoint."""
    if not PINGGY_ENABLED:
        return None
    lock = _get_tunnel_lock(container_name, 'pinggy')
    async with lock:
        try:
            if not await _guest_is_running(container_name, node_id):
                logger.info('Pinggy start skipped for stopped/unavailable VPS %s', container_name)
                return None
            await install_tunnel_supervisors(container_name, node_id)
            await _exec_guest_bash(container_name, node_id, 'rm -f /var/lib/rgnodes/pinggy.info /var/lib/rgnodes/pinggy.pid', timeout=10)
            await _run_tunnel_control(container_name, node_id, 'restart', 'pinggy', timeout=50)
            poll_script = r'''set +e
for _ in $(seq 1 75); do
  info=$(cat /var/lib/rgnodes/pinggy.info 2>/dev/null || true)
  log=$(tail -n 80 /var/lib/rgnodes/pinggy.log 2>/dev/null || true)
  combined="$info
$log"
  endpoint=$(printf '%s\n' "$combined" | sed -E 's/\\x1B\[[0-9;]*[[:alpha:]]//g' | grep -Eo '[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9-]{2,}(\.[A-Za-z0-9-]{2,})+:[0-9]{2,5}' | grep -vE 'free\.pinggy\.io:' | head -n1)
  [ -n "$endpoint" ] || endpoint=$(printf '%s\n' "$combined" | sed -E 's/\\x1B\[[0-9;]*[[:alpha:]]//g' | grep -Eo 'tcp://[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9-]{2,}(\.[A-Za-z0-9-]{2,})+:[0-9]{2,5}' | grep -vE 'free\.pinggy\.io:' | head -n1)
  [ -n "$endpoint" ] || endpoint=$(printf '%s\n' "$combined" | sed -E 's/\\x1B\[[0-9;]*[[:alpha:]]//g' | grep -Eo '[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9-]{2,}(\.[A-Za-z0-9-]{2,})+:[0-9]{2,5}' | grep -vE '^free\.pinggy\.io:' | head -n1)
  if [ -n "$endpoint" ]; then printf '%s\n' "$endpoint"; exit 0; fi
  sleep 1
done
printf 'PINGGY_TIMEOUT\n'
printf '%s\n' "$log"
exit 0
'''
            output = await _exec_guest_bash(container_name, node_id, poll_script, timeout=min(max(TUNNEL_START_TIMEOUT, 90), 120))
            host, port, url = parse_pinggy_endpoint(str(output or ''))
            if not (host and port):
                logger.warning(f'Pinggy endpoint was not produced for {container_name}: {str(output)[-1800:]}')
                return None
            result = {'host': host, 'port': port, 'url': url}
            for items in vps_data.values():
                for vps in items:
                    if str(vps.get('container_name')) == str(container_name):
                        vps['pinggy_host'] = host
                        vps['pinggy_port'] = port
                        vps['pinggy_url'] = url
                        vps['pinggy_started_at'] = datetime.now().isoformat()
                        try:
                            pid_out = await _exec_guest_bash(container_name, node_id, 'cat /var/lib/rgnodes/pinggy.pid 2>/dev/null || true', timeout=10)
                            vps['pinggy_pid'] = int(str(pid_out).strip()) if str(pid_out).strip().isdigit() else None
                        except Exception:
                            vps['pinggy_pid'] = None
                        save_vps_data_immediate()
                        break
            return result
        except Exception as e:
            logger.warning(f'Pinggy session failed for {container_name}: {e}', exc_info=True)
            return None
async def get_pinggy_session_info(container_name: str, node_id: int) -> tuple[Optional[str], Optional[int], bool]:
    script = 'set +e\nsystemd_ok=false\n[ -d /run/systemd/system ] && [ "$(cat /proc/1/comm 2>/dev/null)" = "systemd" ] && systemd_ok=true\nactive=false\nif [ "$systemd_ok" = true ] && systemctl is-active --quiet rgnodes-pinggy.service; then active=true; fi\nsup_pid=$(cat /var/lib/rgnodes/pinggy.supervisor.pid 2>/dev/null | head -n1)\nif [ -n "$sup_pid" ] && kill -0 "$sup_pid" >/dev/null 2>&1; then active=true; fi\npid=$(cat /var/lib/rgnodes/pinggy.pid 2>/dev/null | head -n1)\nif [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then active=true; fi\nprintf \'%s\\n\' "$active"\ncat /var/lib/rgnodes/pinggy.info 2>/dev/null || true\n'
    try:
        output = await _exec_guest_bash(container_name, node_id, script, timeout=20)
        lines = [x.strip() for x in str(output or '').splitlines() if x.strip()]
        active = bool(lines and lines[0].lower() == 'true')
        host, port, _ = parse_pinggy_endpoint('\n'.join(lines[1:]))
        return (host, port, active and bool(host and port))
    except Exception:
        return (None, None, False)
def _png_rgba(width: int, height: int, pixels: bytearray) -> bytes:
    """Encode RGBA pixels to a tiny dependency-free PNG."""
    import struct, zlib
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(pixels[y * stride:(y + 1) * stride])

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 4294967295)
    header = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b'')
def _draw_disc(pix: bytearray, size: int, cx: int, cy: int, r: int, rgba):
    rr = r * r
    for y in range(max(0, cy - r), min(size, cy + r + 1)):
        for x in range(max(0, cx - r), min(size, cx + r + 1)):
            if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= rr:
                i = (y * size + x) * 4
                pix[i:i + 4] = bytes(rgba)
def _draw_rect(pix: bytearray, size: int, x0: int, y0: int, x1: int, y1: int, rgba):
    for y in range(max(0, y0), min(size, y1 + 1)):
        for x in range(max(0, x0), min(size, x1 + 1)):
            i = (y * size + x) * 4
            pix[i:i + 4] = bytes(rgba)
def _draw_line(pix: bytearray, size: int, x0: int, y0: int, x1: int, y1: int, width: int, rgba):
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    for n in range(steps + 1):
        x = round(x0 + (x1 - x0) * n / steps)
        y = round(y0 + (y1 - y0) * n / steps)
        _draw_disc(pix, size, x, y, max(1, width // 2), rgba)
def _builtin_emoji_gif(key: str, size: int=96) -> bytes | None:
    """Create a tiny animated emoji when Pillow is available; return None otherwise."""
    try:
        from PIL import Image, ImageDraw
        import io
        size = max(64, min(96, int(size)))
        frames = []
        for phase in (0, 1, 0, 2):
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            scale = 1.0 + phase * 0.035
            r = int(size * 0.4 * scale)
            cx = cy = size // 2
            bg = {'online': (46, 204, 113, 255), 'status': (46, 204, 113, 255), 'success': (46, 204, 113, 255), 'start': (46, 204, 113, 255), 'pinggy': (46, 204, 113, 255), 'offline': (231, 76, 60, 255), 'error': (231, 76, 60, 255), 'delete': (192, 57, 43, 255), 'stop': (231, 76, 60, 255), 'pinggy_offline': (231, 76, 60, 255), 'warning': (241, 196, 15, 255), 'maintenance': (231, 76, 60, 255), 'loading': (52, 152, 219, 255), 'vps': (155, 89, 182, 255), 'server': (52, 73, 94, 255), 'ssh': (127, 140, 141, 255), 'ports': (230, 126, 34, 255), 'password': (243, 156, 18, 255)}.get(key, (52, 152, 219, 255))
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=bg)
            rr = max(2, int(size * 0.045))
            draw.ellipse((cx - int(size * 0.1), cy - int(size * 0.1), cx + int(size * 0.1), cy + int(size * 0.1)), fill=(255, 255, 255, 255))
            draw.line((cx - int(size * 0.06), cy, cx + int(size * 0.1), cy), fill=bg, width=rr)
            frames.append(img)
        out = io.BytesIO()
        frames[0].save(out, format='GIF', save_all=True, append_images=frames[1:], duration=180, loop=0, disposal=2, optimize=True)
        return out.getvalue()
    except Exception:
        return None
def _builtin_emoji_png(key: str, size: int=96) -> bytes:
    """Generate a compact, consistent server emoji without Pillow or image files."""
    size = max(64, min(128, int(size)))
    pix = bytearray(b'\x00' * (size * size * 4))
    cx = cy = size // 2
    bg_map = {'online': (46, 204, 113, 255), 'status': (46, 204, 113, 255), 'success': (46, 204, 113, 255), 'start': (46, 204, 113, 255), 'pinggy': (46, 204, 113, 255), 'offline': (231, 76, 60, 255), 'error': (231, 76, 60, 255), 'delete': (192, 57, 43, 255), 'stop': (231, 76, 60, 255), 'pinggy_offline': (231, 76, 60, 255), 'warning': (241, 196, 15, 255), 'maintenance': (231, 76, 60, 255), 'loading': (52, 152, 219, 255), 'vps': (155, 89, 182, 255), 'deploy': (52, 152, 219, 255), 'rocket': (52, 152, 219, 255), 'server': (52, 73, 94, 255), 'cpu': (26, 188, 156, 255), 'ram': (52, 152, 219, 255), 'disk': (149, 165, 166, 255), 'network': (22, 160, 133, 255), 'docker': (41, 128, 185, 255), 'ssh': (127, 140, 141, 255), 'ports': (230, 126, 34, 255), 'password': (243, 156, 18, 255), 'reinstall': (142, 68, 173, 255), 'renew': (39, 174, 96, 255), 'stats': (52, 152, 219, 255), 'refresh': (52, 152, 219, 255)}
    bg = bg_map.get(key, (96, 125, 139, 255))
    white = (255, 255, 255, 255)
    _draw_disc(pix, size, cx, cy, int(size * 0.45), bg)
    if key in {'online', 'status', 'success', 'start', 'pinggy'}:
        _draw_disc(pix, size, cx, cy, int(size * 0.18), white)
        _draw_disc(pix, size, cx, cy, int(size * 0.08), bg)
    elif key in {'offline', 'error', 'delete', 'stop', 'pinggy_offline'}:
        w = max(4, int(size * 0.09))
        _draw_line(pix, size, int(size * 0.32), int(size * 0.32), int(size * 0.68), int(size * 0.68), w, white)
        _draw_line(pix, size, int(size * 0.68), int(size * 0.32), int(size * 0.32), int(size * 0.68), w, white)
    elif key in {'warning', 'maintenance'}:
        _draw_rect(pix, size, int(size * 0.47), int(size * 0.3), int(size * 0.53), int(size * 0.58), white)
        _draw_disc(pix, size, cx, int(size * 0.68), max(2, int(size * 0.045)), white)
    elif key in {'vps', 'server', 'docker'}:
        _draw_rect(pix, size, int(size * 0.28), int(size * 0.31), int(size * 0.72), int(size * 0.69), white)
        _draw_rect(pix, size, int(size * 0.34), int(size * 0.39), int(size * 0.66), int(size * 0.45), bg)
        _draw_rect(pix, size, int(size * 0.34), int(size * 0.51), int(size * 0.66), int(size * 0.57), bg)
        _draw_disc(pix, size, int(size * 0.38), int(size * 0.62), 3, white)
    elif key == 'cpu':
        _draw_rect(pix, size, int(size * 0.34), int(size * 0.34), int(size * 0.66), int(size * 0.66), white)
        _draw_rect(pix, size, int(size * 0.29), int(size * 0.43), int(size * 0.33), int(size * 0.49), white)
        _draw_rect(pix, size, int(size * 0.67), int(size * 0.43), int(size * 0.71), int(size * 0.49), white)
    elif key == 'ram':
        for y in (int(size * 0.36), int(size * 0.49), int(size * 0.62)):
            _draw_rect(pix, size, int(size * 0.29), y, int(size * 0.71), y + int(size * 0.07), white)
    elif key == 'disk':
        _draw_disc(pix, size, cx, int(size * 0.48), int(size * 0.18), white)
        _draw_rect(pix, size, int(size * 0.3), int(size * 0.53), int(size * 0.7), int(size * 0.62), white)
        _draw_disc(pix, size, cx, int(size * 0.48), int(size * 0.07), bg)
    elif key in {'network', 'ports'}:
        a = (int(size * 0.35), int(size * 0.6))
        b = (int(size * 0.63), int(size * 0.36))
        c = (int(size * 0.66), int(size * 0.65))
        _draw_line(pix, size, *a, *b, int(size * 0.05), white)
        _draw_line(pix, size, *b, *c, int(size * 0.05), white)
        _draw_disc(pix, size, *a, int(size * 0.1), white)
        _draw_disc(pix, size, *b, int(size * 0.1), white)
        _draw_disc(pix, size, *c, int(size * 0.1), white)
    elif key == 'ssh':
        _draw_disc(pix, size, cx, cy, int(size * 0.22), white)
        _draw_line(pix, size, int(size * 0.38), int(size * 0.5), int(size * 0.58), int(size * 0.5), int(size * 0.05), bg)
        _draw_line(pix, size, int(size * 0.5), int(size * 0.38), int(size * 0.5), int(size * 0.62), int(size * 0.05), bg)
    elif key == 'password':
        _draw_disc(pix, size, int(size * 0.42), int(size * 0.47), int(size * 0.13), white)
        _draw_rect(pix, size, int(size * 0.48), int(size * 0.44), int(size * 0.7), int(size * 0.54), white)
    elif key == 'refresh':
        _draw_line(pix, size, int(size * 0.35), int(size * 0.6), int(size * 0.35), int(size * 0.42), int(size * 0.07), white)
        _draw_line(pix, size, int(size * 0.35), int(size * 0.42), int(size * 0.5), int(size * 0.32), int(size * 0.07), white)
        _draw_line(pix, size, int(size * 0.65), int(size * 0.4), int(size * 0.65), int(size * 0.58), int(size * 0.07), white)
        _draw_line(pix, size, int(size * 0.65), int(size * 0.58), int(size * 0.5), int(size * 0.68), int(size * 0.07), white)
    elif key in {'rocket', 'deploy'}:
        _draw_line(pix, size, int(size * 0.36), int(size * 0.66), int(size * 0.6), int(size * 0.34), int(size * 0.1), white)
        _draw_disc(pix, size, int(size * 0.56), int(size * 0.44), int(size * 0.06), bg)
    elif key == 'stats':
        _draw_rect(pix, size, int(size * 0.32), int(size * 0.54), int(size * 0.41), int(size * 0.68), white)
        _draw_rect(pix, size, int(size * 0.45), int(size * 0.43), int(size * 0.54), int(size * 0.68), white)
        _draw_rect(pix, size, int(size * 0.58), int(size * 0.32), int(size * 0.71), int(size * 0.68), white)
    elif key == 'loading':
        _draw_disc(pix, size, cx, cy, int(size * 0.23), white)
        _draw_line(pix, size, cx, cy, int(size * 0.6), int(size * 0.42), int(size * 0.05), bg)
    elif key in {'renew', 'reinstall'}:
        _draw_line(pix, size, int(size * 0.33), int(size * 0.55), int(size * 0.48), int(size * 0.68), int(size * 0.08), white)
        _draw_line(pix, size, int(size * 0.48), int(size * 0.68), int(size * 0.7), int(size * 0.36), int(size * 0.08), white)
    else:
        _draw_disc(pix, size, cx, cy, int(size * 0.12), white)
    return _png_rgba(size, size, pix)
async def auto_provision_server_emojis(guild: discord.Guild) -> None:
    """Idempotently create the configured AXIONHOST emoji pack without restart duplicates.

    Discord's full server emoji list is authoritative. If it cannot be fetched, fail closed
    rather than creating duplicates from a possibly incomplete local cache.
    """
    if not AUTO_CREATE_SERVER_EMOJIS:
        return
    async with EMOJI_PROVISION_LOCK:
        try:
            me = guild.me
            if not me or not me.guild_permissions.manage_emojis_and_stickers:
                logger.info('Emoji auto-provision skipped for %s: Manage Expressions is unavailable.', guild.name)
                return
            try:
                fetched = await guild.fetch_emojis()
            except (discord.HTTPException, discord.Forbidden, asyncio.TimeoutError) as exc:
                logger.warning('Emoji creation skipped for %s because the authoritative emoji list could not be fetched (%s); retry on next ready event.', guild.name, type(exc).__name__)
                return
            existing = {str(e.name).casefold(): e for e in fetched}
            emoji_limit = max(0, int(getattr(guild, 'emoji_limit', 50)))
            available = max(0, emoji_limit - len(fetched))
            created = 0
            configured_seen = set()
            for key, configured in CUSTOM_EMOJI_NAMES.items():
                raw = str(configured or '').strip()
                if not raw or re.fullmatch('<a?:[A-Za-z0-9_]{2,32}:\\d+>', raw):
                    continue
                safe_name = re.sub('[^A-Za-z0-9_]', '_', raw)[:32]
                folded = safe_name.casefold()
                if len(safe_name) < 2 or folded in configured_seen:
                    continue
                configured_seen.add(folded)
                if folded in existing:
                    continue
                if available <= 0:
                    break
                try:
                    animated_image = _builtin_emoji_gif(key)
                    try:
                        emoji = await guild.create_custom_emoji(name=safe_name, image=animated_image or _builtin_emoji_png(key), reason=f'{BOT_NAME} automatic emoji pack')
                    except discord.HTTPException as create_exc:
                        refresh_ok = False
                        try:
                            refreshed = await guild.fetch_emojis()
                            refresh_ok = True
                            refreshed_map = {str(e.name).casefold(): e for e in refreshed}
                            if folded in refreshed_map:
                                existing.update(refreshed_map)
                                available = max(0, emoji_limit - len(refreshed))
                                continue
                        except Exception as refresh_exc:
                            logger.warning('Emoji create state uncertain for %s in %s; no duplicate retry (%s).', safe_name, guild.name, type(refresh_exc).__name__)
                        if not refresh_ok or animated_image is None:
                            raise create_exc
                        emoji = await guild.create_custom_emoji(name=safe_name, image=_builtin_emoji_png(key), reason=f'{BOT_NAME} automatic emoji pack (static fallback)')
                    existing[str(emoji.name).casefold()] = emoji
                    available = max(0, available - 1)
                    created += 1
                    await asyncio.sleep(1.2)
                except discord.Forbidden as exc:
                    logger.warning('Emoji auto-provision forbidden in %s: %s', guild.name, exc)
                    break
                except discord.HTTPException as exc:
                    retry_after = float(getattr(exc, 'retry_after', 3.0) or 3.0)
                    await asyncio.sleep(min(20.0, max(2.0, retry_after)))
                    logger.warning('Emoji creation failed for %s in %s (%s).', safe_name, guild.name, type(exc).__name__)
                except Exception as exc:
                    logger.warning('Emoji creation failed for %s (%s).', safe_name, type(exc).__name__)
            logger.info('Emoji provisioning completed for %s: created=%d, available_slots=%d', guild.name, created, available)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception('Emoji auto-provision crashed for %s (%s)', getattr(guild, 'name', guild.id), type(exc).__name__)
def resolve_custom_emoji(key: str, fallback: str='') -> str:
    """Return a server custom emoji when available, otherwise a Unicode fallback."""
    raw = str(CUSTOM_EMOJI_NAMES.get(key, '') or '').strip()
    if re.fullmatch('<a?:[A-Za-z0-9_]{2,32}:\\d+>', raw):
        return raw
    try:
        cached = discord.utils.get(bot.emojis, name=raw) if raw else None
        if cached:
            return str(cached)
    except Exception:
        pass
    return fallback
def _safe_diagnostic_text(error, limit=900):
    """Redact common secrets/tunnel URLs before writing a useful failure reason to service logs."""
    value = str(error if error is not None else 'Unknown failure')
    value = re.sub('(?i)https?://[^\\s/]*pinggy[^\\s/]*/[^\\s<>`]*', '[TUNNEL_URL_REDACTED]', value)
    value = re.sub('(?i)tcp://[^\\s<>`]+', '[TUNNEL_ENDPOINT_REDACTED]', value)
    value = re.sub('(?i)discord(?:app)?\\.com/api/webhooks/[^\\s<>`]+', '[DISCORD_WEBHOOK_REDACTED]', value)
    value = re.sub('(?i)(token|api[_ -]?key|password|passwd|secret|authorization)(\\s*[=:]\\s*)[^\\s,;]+', '\\1\\2[REDACTED]', value)
    value = re.sub('(?i)(--?(?:password|passwd|token|api[-_]?key|secret|authorization)(?:=|\\s+))(?:(?:\'[^\']*\')|(?:"[^"]*")|[^\\s,;]+)', '\\1[REDACTED]', value)
    value = re.sub('(?i)(?:Bot\\s+)?[A-Za-z0-9_-]{20,}\\.[A-Za-z0-9_-]{5,}\\.[A-Za-z0-9_-]{10,}', '[TOKEN_REDACTED]', value)
    return truncate_text(value.replace('\x00', ' '), limit)
def safe_error_summary(operation, error=None, trace_id=None):
    """Safe Discord-facing failure summary without exception text or response payloads."""
    action = str(operation or 'Operation').strip()[:120]
    error_name = type(error).__name__ if isinstance(error, BaseException) else 'UnknownError'
    trace = f' Diagnostic ID: `{trace_id}`.' if trace_id else ''
    return f'{action} failed ({error_name}). Sensitive details were hidden; an administrator can search service logs using the diagnostic ID.{trace}'
def _configured_default_node_id() -> int:
    """Return the persisted default deployment node, falling back to the env value."""
    try:
        persisted = int(str(get_setting('default_node_id', '0') or '0').strip())
    except (TypeError, ValueError):
        persisted = 0
    if persisted > 0:
        return persisted
    return DEFAULT_NODE_ID if DEFAULT_NODE_ID > 0 else 0


async def _probe_remote_node(node: Dict[str, Any], attempts: int = 3, timeout: float = 4.0) -> tuple[bool, str, float]:
    """Authenticated, non-blocking remote-node health probe.

    Supports both current X-API-Key authentication and the legacy api_key query
    parameter used by older node agents. Never logs the secret.
    """
    if not node or bool(node.get("is_local")):
        return False, "local node", 0.0
    raw_url = str(node.get("url") or "").strip().rstrip("/")
    api_key = str(node.get("api_key") or "").strip()
    if not raw_url:
        return False, "missing URL", 0.0
    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, "invalid URL", 0.0
    if not api_key:
        return False, "missing API key", 0.0
    endpoint = raw_url + "/api/ping"
    headers = {"X-API-Key": api_key, "User-Agent": _make_discord_user_agent(BOT_NAME, BOT_VERSION)}
    last = "unreachable"
    for attempt in range(max(1, attempts)):
        started = time.monotonic()
        try:
            response = await http_request("GET", endpoint, headers=headers, params={"api_key": api_key}, timeout=timeout)
            latency = (time.monotonic() - started) * 1000.0
            if response.status_code != 200:
                last = f"HTTP {response.status_code}"
            else:
                try:
                    payload = response.json()
                except Exception:
                    payload = {}
                if isinstance(payload, dict) and payload.get("status") in (None, "ok", "online", "healthy"):
                    return True, "online", latency
                return True, "online", latency
        except Exception as exc:
            last = f"{type(exc).__name__}: {str(exc)[:120]}"
        if attempt + 1 < max(1, attempts):
            await asyncio.sleep(min(0.5 * (2 ** attempt), 2.0))
    return False, last, 0.0

def _remote_candidates() -> list[Dict[str, Any]]:
    return sorted([n for n in get_nodes() if not bool(n.get("is_local"))], key=lambda n: int(n.get("id") or 0))

def _preferred_deployment_node_id() -> int:
    """Return the deployment node according to the explicit routing policy.

    Default AxionHost mode is LOCAL-CONTROLLER mode: the local LXD controller
    (normally Node 1) creates/manages VPSs directly. Remote-only mode is opt-in
    via REMOTE_NODE_ONLY=true and then a healthy remote node is mandatory.
    """
    nodes = get_nodes()
    if not nodes:
        raise RuntimeError("No VPS node is configured. Create a node first.")

    if REMOTE_NODE_ONLY:
        candidates = [n for n in nodes if not bool(n.get("is_local"))]
        if not candidates:
            raise RuntimeError("Remote-only mode is enabled, but no remote VPS node is configured. Set REMOTE_NODE_ONLY=false to use the local controller, or create a remote node.")
        configured_id = _configured_default_node_id()
        selected = next((n for n in candidates if int(n.get("id") or 0) == configured_id), None) if configured_id > 0 else None
        if selected is None:
            raise RuntimeError("Remote-only mode is enabled, but the configured default is not a remote node. Set a healthy remote node with `node default <id>` or disable REMOTE_NODE_ONLY.")
        return int(selected["id"])

    # Normal/local-controller mode. Always prefer the actual local controller,
    # even if an old database still contains a remote node as default.
    local_nodes = [n for n in nodes if bool(n.get("is_local"))]
    if local_nodes:
        selected_id = int(sorted(local_nodes, key=lambda n: int(n.get("id") or 0))[0]["id"])
        if _configured_default_node_id() != selected_id:
            try:
                set_setting("default_node_id", str(selected_id))
                logger.info("Local-controller mode: repaired deployment default to local node %s", selected_id)
            except Exception:
                logger.exception("Failed to persist local controller as default node")
        return selected_id

    configured_id = _configured_default_node_id()
    if configured_id > 0 and get_node(configured_id):
        return configured_id
    selected_id = int(sorted(nodes, key=lambda n: int(n.get("id") or 0))[0]["id"])
    try:
        set_setting("default_node_id", str(selected_id))
    except Exception:
        logger.exception("Failed to persist fallback deployment node")
    return selected_id

def _resolve_execution_node_id(container_name: str = "") -> int:
    """Resolve existing VPS ownership; new VPSs use the local controller by default."""
    if container_name:
        try:
            with DB_LOCK:
                conn = get_db()
                try:
                    row = conn.execute("SELECT node_id FROM vps WHERE container_name = ?", (str(container_name),)).fetchone()
                finally:
                    conn.close()
            if row and row[0] is not None:
                mapped = int(row[0])
                mapped_node = get_node(mapped)
                if mapped_node:
                    if REMOTE_NODE_ONLY and bool(mapped_node.get("is_local")):
                        logger.warning("Existing VPS %s has local node mapping %s under remote-only mode; using remote default.", container_name, mapped)
                    else:
                        return mapped
        except Exception as exc:
            logger.warning("Could not resolve existing VPS node mapping (%s); using deployment default.", type(exc).__name__)
    return _preferred_deployment_node_id()

async def execute_vpsctl_compat(container_name: str, command: str, timeout: int=300, node_id: Optional[int]=None):
    """Execute one AXIONHOST LXD VPS compat command locally or through an authenticated node agent."""
    if node_id is None:
        node_id = _resolve_execution_node_id(container_name)
    node = get_node(node_id)
    if not node:
        raise RuntimeError(f'Node {node_id} not found')
    if REMOTE_NODE_ONLY and bool(node.get('is_local')):
        requested_node_id = node_id
        node_id = _preferred_deployment_node_id()
        node = get_node(node_id)
        if not node or bool(node.get('is_local')):
            raise RuntimeError('Remote-only mode is enabled, but no reachable remote node is configured. Set REMOTE_NODE_ONLY=false to use the local controller, or configure a healthy remote node.')
        logger.warning('REMOTE_NODE_ONLY redirected VPS operation from local node_id=%s to remote node_id=%s', requested_node_id, node_id)
    command = str(command or '').strip()
    if not command:
        raise ValueError('VPS controller command cannot be empty')
    if node.get('is_local'):
        controller = _find_kvm_vpsctl()
        if not controller:
            raise RuntimeError('LXD controller executable is missing or invalid. Run `sudo bash setup.sh --repair-controller` from the matching seven-file release directory (or `sudo bash setup.sh` for a full install). The installer verifies the embedded SHA-256 and preserves the old controller; legacy LXC/LXD controllers are intentionally rejected.')
        argv = [sys.executable, controller, 'compat', command]
        try:
            # Keep the controller and all of its LXD/bash descendants in one process group.
            # This prevents orphaned children from keeping stdout/stderr pipes open after a timeout.
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=max(5, int(timeout)))
            except asyncio.TimeoutError:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except OSError:
                    try: proc.kill()
                    except ProcessLookupError: pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    except OSError:
                        try: proc.kill()
                        except ProcessLookupError: pass
                    try: await asyncio.wait_for(proc.wait(), timeout=2)
                    except asyncio.TimeoutError: pass
                raise asyncio.TimeoutError(f'VPS operation timed out after {timeout}s')
            except asyncio.CancelledError:
                try: os.killpg(proc.pid, signal.SIGTERM)
                except Exception:
                    try: proc.kill()
                    except ProcessLookupError: pass
                try: await asyncio.wait_for(proc.wait(), timeout=3)
                except Exception:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except Exception: pass
                raise
        except FileNotFoundError as exc:
            raise RuntimeError(f'Python/controller executable unavailable: {controller}') from exc
        out = stdout.decode(errors='replace').strip() if stdout else ''
        err = stderr.decode(errors='replace').strip() if stderr else ''
        if proc.returncode != 0:
            detail = err or out or 'controller returned a failure'
            legacy_lxc_markers = ('Failed getting remote image info', 'requested image couldn', 'LXC', 'LXD')
            if any((marker.lower() in detail.lower() for marker in legacy_lxc_markers)):
                detail = f'A legacy LXC/LXD controller appears to be installed or being selected. AXIONHOST now requires the LXD/LXC vpsctl.py controller. Run setup.sh and keep the current vpsctl.py beside bot.py. Original controller error: {detail[:900]}'
            raise RuntimeError(f'Local VPS operation failed: {detail}')
        if out:
            try:
                payload = json.loads(out)
                if isinstance(payload, dict) and payload.get('error'):
                    raise RuntimeError(str(payload['error']))
                if isinstance(payload, (dict, list)):
                    return payload
            except json.JSONDecodeError:
                pass
        return out if out else True
    url = str(node.get('url') or '').rstrip('/') + '/api/execute'
    api_key = str(node.get('api_key') or '')
    if not url or not api_key:
        raise RuntimeError(f"Remote node {node.get('name', node_id)!r} is missing URL/API key")
    remote_controller = str(node.get('vpsctl_path') or '/usr/local/sbin/vpsctl')
    full_command = f'{shlex.quote(remote_controller)} compat {shlex.quote(command)}'
    try:
        response = await asyncio.to_thread(requests.post, url, json={'command': full_command}, headers={'X-API-Key': api_key}, timeout=timeout)
    except requests.exceptions.Timeout as exc:
        raise RuntimeError(f"Remote VPS operation timed out on {node.get('name', node_id)} after {timeout}s") from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Remote node {node.get('name', node_id)} is unreachable: {exc}") from exc
    if response.status_code != 200:
        try:
            payload = response.json()
            detail = payload.get('detail') or payload.get('error') or payload.get('stderr') or payload
        except Exception:
            detail = response.text
        raise RuntimeError(f"Remote VPS operation failed on {node.get('name', node_id)} (HTTP {response.status_code}): {str(detail)[:1500]}")
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"Remote node {node.get('name', node_id)} returned invalid JSON") from exc
    rc = int(payload.get('returncode', payload.get('return_code', 0)) or 0)
    if rc != 0:
        raise RuntimeError(f"Remote VPS operation failed on {node.get('name', node_id)}: {str(payload.get('stderr') or payload.get('error') or 'command failed')[:1600]}")
    out = str(payload.get('stdout') or '')
    try:
        parsed = json.loads(out)
        if isinstance(parsed, (dict, list)):
            return parsed
    except Exception:
        pass
    return out if out else True
async def execute_vpsctl(subcommand: str, action: str, container_name: str, timeout: int=300, node_id: Optional[int]=None):
    """Compatibility wrapper used by legacy stats callers; never invokes a container backend; only LXD/LXC VPS operations are supported."""
    if subcommand == 'compat':
        return await execute_vpsctl_compat(container_name, action, timeout=timeout, node_id=node_id)
    raise RuntimeError(f'Unsupported VPS controller mode: {subcommand}')
async def _exec_guest_bash(container_name: str, node_id: int, script: str, timeout: int=120):
    """Run a guest script only when the target LXC is actually running."""
    payload = str(script or '').strip()
    if not payload:
        return ''
    if not await _guest_is_running(container_name, node_id):
        raise RuntimeError(f'VPS `{container_name}` is not running or is unavailable on node {node_id}.')
    return await execute_vpsctl_compat(
        container_name,
        f'exec {shlex.quote(container_name)} -- bash -lc {shlex.quote(payload)}',
        timeout=timeout, node_id=node_id
    )
async def apply_vps_performance_profile(container_name: str, node_id: int, ram_mb: int, cpu: int) -> None:
    """LXD container resource ceiling policy. Runtime starts small; max CPU/RAM stay admitted and bounded."""
    ram_mb = max(1024, min(VPS_MAX_RAM_GB * 1024, int(ram_mb)))
    cpu = max(1, min(VPS_MAX_CPU, int(cpu)))
    await execute_vpsctl_compat(container_name, f'config set {shlex.quote(container_name)} limits.memory.max {ram_mb}MB', node_id=node_id, timeout=60)
    await execute_vpsctl_compat(container_name, f'config set {shlex.quote(container_name)} limits.cpu.max {cpu}', node_id=node_id, timeout=60)
async def apply_vps_vm_config(container_name: str, node_id: int) -> bool:
    """LXD container config is applied by vpsctl; this hook is intentionally non-destructive."""
    return True
def _cleanup_orphaned_rgnodes_temp_files(max_files: int=32) -> int:
    """Delete only stale atomic-write temp files owned by this app; never clean OS /tmp."""
    removed = 0
    now = time.time()
    try:
        candidates = list(DATA_DIR.iterdir())
    except OSError:
        return 0
    for path in candidates:
        if removed >= max(1, min(64, int(max_files))):
            break
        if path.is_symlink() or not path.is_file():
            continue
        match = re.fullmatch('\\..+\\.rgnodes-(\\d+)\\.tmp', path.name)
        if not match:
            continue
        try:
            if now - path.stat(follow_symlinks=False).st_mtime < 3600:
                continue
            pid = int(match.group(1))
            if pid > 0:
                try:
                    os.kill(pid, 0)
                    continue
                except ProcessLookupError:
                    pass
                except PermissionError:
                    continue
                except OSError:
                    continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed
def _opportunistic_sqlite_maintenance() -> bool:
    """Run inexpensive SQLite housekeeping only when the DB lock is immediately available."""
    if not DB_LOCK.acquire(blocking=False):
        return False
    conn = None
    try:
        conn = get_db()
        conn.execute('PRAGMA optimize')
        conn.execute('PRAGMA wal_checkpoint(PASSIVE)')
        return True
    except sqlite3.Error as exc:
        logger.debug('SQLite housekeeping deferred (%s).', type(exc).__name__)
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        DB_LOCK.release()
async def resource_housekeeping_task():
    """Five-minute low-load cleanup; preserve kernel caches, VM disks, logs and backups."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(300)
        try:
            now_mono = time.monotonic()
            stale_cache_after = max(60.0, HOST_STATS_CACHE_TTL * 10.0)
            stale_nodes = [node_id for node_id, (stamp, _value) in list(HOST_STATS_CACHE.items()) if now_mono - float(stamp) > stale_cache_after]
            for node_id in stale_nodes:
                HOST_STATS_CACHE.pop(node_id, None)
            attempts = globals().get('_WEB_TERMINAL_LOGIN_ATTEMPTS')
            if isinstance(attempts, dict):
                for remote, stamps in list(attempts.items()):
                    active = [float(stamp) for stamp in stamps if now_mono - float(stamp) < 300.0]
                    if active:
                        attempts[remote] = active
                    else:
                        attempts.pop(remote, None)
            active_locks = set()
            for items in list(vps_data.values()):
                if not isinstance(items, (list, tuple)):
                    continue
                for vps in list(items):
                    if not isinstance(vps, dict):
                        continue
                    name = str(vps.get('container_name') or '').strip()
                    if not name:
                        continue
                    try:
                        node_id = int(vps.get('node_id', 1) or 1)
                    except (TypeError, ValueError):
                        continue
                    active_locks.add((name, node_id))
            for key, lock in list(TUNNEL_SETUP_LOCKS.items()):
                if key not in active_locks and (not lock.locked()):
                    TUNNEL_SETUP_LOCKS.pop(key, None)
            removed = await asyncio.to_thread(_cleanup_orphaned_rgnodes_temp_files)
            try:
                gc.collect(0)
            except Exception:
                pass
            sqlite_ok = await asyncio.to_thread(_opportunistic_sqlite_maintenance)
            if stale_nodes or removed or sqlite_ok:
                logger.debug('Housekeeping complete: stale_node_cache=%d orphan_tmp=%d sqlite_maintenance=%s', len(stale_nodes), removed, sqlite_ok)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('Five-minute housekeeping skipped (%s).', type(exc).__name__)
def cleanup_on_shutdown():
    try:
        save_vps_data()
        save_admin_data()
    except Exception as exc:
        logger.error('Final database save failed: %s', exc, exc_info=True)
        try:
            backup_database()
        except Exception:
            pass
def get_presence_counts():
    created = sum((len(items) for items in vps_data.values()))
    running = sum((1 for items in vps_data.values() for v in items if str(v.get('status', '')).lower() == 'running' and (not v.get('suspended', False))))
    expired = sum((1 for items in vps_data.values() for v in items if v.get('expiration_date') and _safe_fromiso(str(v['expiration_date'])) <= datetime.now()))
    total_slots = sum((max(0, int(n.get('total_vps') or 0)) for n in get_nodes())) or max(created, 1)
    return (created, total_slots, running, expired)
def _load_web_terminal_secret() -> tuple[str, str]:
    global _WEB_TERMINAL_TOKEN_CACHE
    if _WEB_TERMINAL_TOKEN_CACHE:
        return _WEB_TERMINAL_TOKEN_CACHE
    if WEB_TERMINAL_TOKEN:
        if len(WEB_TERMINAL_TOKEN) < 32:
            raise RuntimeError('WEB_TERMINAL_TOKEN must be at least 32 characters; unset it to create a private token file.')
        _WEB_TERMINAL_TOKEN_CACHE = (WEB_TERMINAL_TOKEN, '.env')
        return _WEB_TERMINAL_TOKEN_CACHE
    token_path = DATA_DIR / 'web_terminal.token'
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        if token_path.is_symlink():
            raise RuntimeError('The web terminal token path must not be a symbolic link.')
        if token_path.exists():
            if not token_path.is_file():
                raise RuntimeError('The web terminal token path is not a regular file.')
            token = token_path.read_text(encoding='utf-8').strip()
            if len(token) >= 32:
                os.chmod(token_path, 384)
                _WEB_TERMINAL_TOKEN_CACHE = (token, str(token_path))
                return _WEB_TERMINAL_TOKEN_CACHE
            raise RuntimeError('The existing terminal token file is invalid; remove it and restart to generate a new token.')
        token = secrets.token_urlsafe(48)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        fd = os.open(token_path, flags, 384)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(token + '\n')
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.unlink(token_path)
            except OSError:
                pass
            raise
        os.chmod(token_path, 384)
        _WEB_TERMINAL_TOKEN_CACHE = (token, str(token_path))
        return _WEB_TERMINAL_TOKEN_CACHE
    except OSError as exc:
        raise RuntimeError(f'Could not safely create/read the terminal token file ({type(exc).__name__}).') from exc
def _web_terminal_session_ok(request) -> bool:
    sid = request.cookies.get('rgnodes_terminal_session', '')
    expiry = _WEB_TERMINAL_SESSIONS.get(sid)
    if not expiry:
        return False
    if expiry <= time.monotonic():
        _WEB_TERMINAL_SESSIONS.pop(sid, None)
        return False
    _WEB_TERMINAL_SESSIONS[sid] = time.monotonic() + 3600
    return True
async def _web_terminal_root(_request):
    if aiohttp_web is None:
        raise RuntimeError('aiohttp web support is unavailable')
    return aiohttp_web.Response(text=_WEB_TERMINAL_HTML, content_type='text/html', charset='utf-8')
async def _web_terminal_login(request):
    if aiohttp_web is None:
        raise RuntimeError('aiohttp web support is unavailable')
    remote = str(request.remote or 'unknown')
    try:
        peer = ipaddress.ip_address(remote.split('%', 1)[0])
        if peer.is_loopback:
            forwarded = str(request.headers.get('X-Forwarded-For', '')).split(',', 1)[0].strip()
            if forwarded:
                remote = ipaddress.ip_address(forwarded).compressed
    except ValueError:
        remote = 'invalid-proxy-peer'
    now = time.monotonic()
    recent = [t for t in _WEB_TERMINAL_LOGIN_ATTEMPTS.get(remote, []) if now - t < 300]
    if len(recent) >= 8:
        _WEB_TERMINAL_LOGIN_ATTEMPTS[remote] = recent
        return aiohttp_web.json_response({'error': 'Too many attempts. Wait five minutes.'}, status=429)
    _WEB_TERMINAL_LOGIN_ATTEMPTS[remote] = recent + [now]
    if len(_WEB_TERMINAL_LOGIN_ATTEMPTS) > 1024:
        for candidate, stamps in list(_WEB_TERMINAL_LOGIN_ATTEMPTS.items()):
            active = [stamp for stamp in stamps if now - stamp < 300]
            if active:
                _WEB_TERMINAL_LOGIN_ATTEMPTS[candidate] = active
            else:
                _WEB_TERMINAL_LOGIN_ATTEMPTS.pop(candidate, None)
        if len(_WEB_TERMINAL_LOGIN_ATTEMPTS) > 2048:
            for candidate in list(_WEB_TERMINAL_LOGIN_ATTEMPTS)[:len(_WEB_TERMINAL_LOGIN_ATTEMPTS) - 2048]:
                _WEB_TERMINAL_LOGIN_ATTEMPTS.pop(candidate, None)
    try:
        body = await request.json()
        supplied = str(body.get('token', ''))[:512]
    except Exception:
        supplied = ''
    try:
        expected, _token_source = _load_web_terminal_secret()
    except Exception as exc:
        logger.error('Web terminal token initialization failed: %s', type(exc).__name__)
        return aiohttp_web.json_response({'error': 'Terminal authentication is not configured safely.'}, status=503)
    if not supplied or not secrets.compare_digest(supplied, expected):
        return aiohttp_web.json_response({'error': 'Invalid terminal token.'}, status=401)
    _WEB_TERMINAL_LOGIN_ATTEMPTS.pop(remote, None)
    for old_sid, expiry in list(_WEB_TERMINAL_SESSIONS.items()):
        if expiry <= now:
            _WEB_TERMINAL_SESSIONS.pop(old_sid, None)
    if len(_WEB_TERMINAL_SESSIONS) >= 64:
        return aiohttp_web.json_response({'error': 'Too many authenticated sessions are open. Log out unused sessions first.'}, status=429)
    sid = secrets.token_urlsafe(36)
    _WEB_TERMINAL_SESSIONS[sid] = now + 3600
    response = aiohttp_web.json_response({'ok': True})
    forwarded_proto = str(request.headers.get('X-Forwarded-Proto', '')).split(',', 1)[0].strip().lower()
    secure_cookie = forwarded_proto == 'https' or str(request.host or '').split(':', 1)[0].lower() == 'ssh.rgnodes.bond'
    response.set_cookie('rgnodes_terminal_session', sid, httponly=True, secure=secure_cookie, samesite='Strict', max_age=3600, path='/')
    return response
async def _web_terminal_logout(request):
    if aiohttp_web is None:
        raise RuntimeError('aiohttp web support is unavailable')
    sid = request.cookies.get('rgnodes_terminal_session', '')
    _WEB_TERMINAL_SESSIONS.pop(sid, None)
    response = aiohttp_web.json_response({'ok': True})
    response.del_cookie('rgnodes_terminal_session', path='/')
    return response
async def _web_terminal_websocket(request):
    if aiohttp_web is None:
        raise RuntimeError('aiohttp web support is unavailable')
    if not _web_terminal_session_ok(request):
        return aiohttp_web.Response(status=401, text='Login required')
    ws = aiohttp_web.WebSocketResponse(heartbeat=25, max_msg_size=4096, autoclose=True, autoping=True)
    await ws.prepare(request)
    process = None
    master_fd = None
    reader_task = None
    active_key = None
    try:
        async for message in ws:
            if message.type == aiohttp_web.WSMsgType.ERROR:
                break
            if message.type != aiohttp_web.WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(message.data)
            except (TypeError, ValueError):
                await ws.send_str(json.dumps({'type': 'error', 'data': 'Invalid terminal message.'}))
                continue
            action = str(payload.get('type', ''))
            if action == 'connect':
                if process is not None:
                    await ws.send_str(json.dumps({'type': 'error', 'data': 'A session is already connected on this socket.'}))
                    continue
                if len(_WEB_TERMINAL_ACTIVE_SESSIONS) >= WEB_TERMINAL_MAX_SESSIONS:
                    await ws.send_str(json.dumps({'type': 'error', 'data': 'Terminal session limit reached. Close another session first.'}))
                    continue
                host = str(payload.get('host', '')).strip().strip('[]')
                username = str(payload.get('username', 'root')).strip()
                try:
                    port = int(payload.get('port', 22))
                except (TypeError, ValueError):
                    port = 0
                try:
                    ipaddress.ip_address(host)
                    host_valid = True
                except ValueError:
                    host_valid = bool(re.fullmatch('(?i)(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*', host))
                if not host_valid or not 1 <= port <= 65535 or (not re.fullmatch('[A-Za-z_][A-Za-z0-9._-]{0,31}', username)):
                    await ws.send_str(json.dumps({'type': 'error', 'data': 'Invalid host, port, or username.'}))
                    continue
                ssh_binary = shutil.which('ssh')
                if not ssh_binary:
                    await ws.send_str(json.dumps({'type': 'error', 'data': 'OpenSSH client binary is missing on the AXIONHOST host.'}))
                    continue
                slave_fd = None
                try:
                    import fcntl, pty, signal, struct, termios
                    master_fd, slave_fd = pty.openpty()
                    cols = max(40, min(240, int(payload.get('cols', 100) or 100)))
                    rows = max(12, min(80, int(payload.get('rows', 28) or 28)))
                    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
                    argv = [ssh_binary, '-tt', '-p', str(port), '-o', 'BatchMode=no', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=12', '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3', '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no', '-o', 'ClearAllForwardings=yes', '-o', 'PermitLocalCommand=no', '-o', 'LogLevel=ERROR', '--', f'{username}@{host}']
                    process = await asyncio.create_subprocess_exec(*argv, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, start_new_session=True)
                    os.close(slave_fd)
                    os.set_blocking(master_fd, False)
                    active_key = f'{id(ws)}:{process.pid}'
                    _WEB_TERMINAL_ACTIVE_SESSIONS.add(active_key)
                    await ws.send_str(json.dumps({'type': 'status', 'data': f'Connected to local OpenSSH client · {username}@{host}:{port}. Authenticate in the terminal prompt.'}))

                    async def _pump_pty():
                        loop = asyncio.get_running_loop()
                        while not ws.closed:
                            future = loop.create_future()

                            def _ready():
                                if future.done():
                                    return
                                try:
                                    chunk = os.read(master_fd, 4096)
                                except BlockingIOError:
                                    chunk = None
                                except OSError:
                                    chunk = b''
                                if not future.done():
                                    future.set_result(chunk)
                            try:
                                loop.add_reader(master_fd, _ready)
                                chunk = await future
                            finally:
                                loop.remove_reader(master_fd)
                            if chunk is None:
                                continue
                            if chunk:
                                try:
                                    await ws.send_bytes(chunk)
                                except Exception:
                                    break
                            else:
                                break
                        try:
                            code = await process.wait()
                            if not ws.closed:
                                await ws.send_str(json.dumps({'type': 'status', 'data': f'SSH process ended (exit {code}).', 'done': True}))
                        except Exception:
                            pass
                    reader_task = asyncio.create_task(_pump_pty(), name=f'rgnodes_web_ssh_{process.pid}')
                except Exception as exc:
                    if slave_fd is not None:
                        try:
                            os.close(slave_fd)
                        except OSError:
                            pass
                    if master_fd is not None:
                        try:
                            os.close(master_fd)
                        except OSError:
                            pass
                        master_fd = None
                    await ws.send_str(json.dumps({'type': 'error', 'data': f'Could not start OpenSSH ({type(exc).__name__}).'}))
                continue
            if action == 'input':
                if master_fd is None:
                    await ws.send_str(json.dumps({'type': 'error', 'data': 'Connect to an SSH host first.'}))
                    continue
                data = payload.get('data', '')
                if isinstance(data, str) and len(data) <= 2048:
                    try:
                        os.write(master_fd, data.encode('utf-8', errors='replace'))
                    except OSError:
                        await ws.send_str(json.dumps({'type': 'status', 'data': 'SSH input channel closed.', 'done': True}))
                continue
            if action == 'resize' and master_fd is not None:
                try:
                    import fcntl, signal, struct, termios
                    cols = max(40, min(240, int(payload.get('cols', 100) or 100)))
                    rows = max(12, min(80, int(payload.get('rows', 28) or 28)))
                    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
                    if process is not None:
                        os.killpg(process.pid, signal.SIGWINCH)
                except Exception:
                    pass
    finally:
        if reader_task is not None and (not reader_task.done()):
            reader_task.cancel()
            try:
                await reader_task
            except BaseException:
                pass
        if process is not None and process.returncode is None:
            try:
                import signal
                os.killpg(process.pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), timeout=3)
            except Exception:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except Exception:
                    pass
                try:
                    await process.wait()
                except Exception:
                    pass
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        if active_key:
            _WEB_TERMINAL_ACTIVE_SESSIONS.discard(active_key)
    return ws
async def start_web_terminal_server():
    global _WEB_TERMINAL_RUNNER
    if not WEB_TERMINAL_ENABLED:
        logger.info('AXIONHOST web terminal is disabled by configuration.')
        return
    if _WEB_TERMINAL_RUNNER is not None:
        return
    if aiohttp_web is None:
        logger.warning('AXIONHOST web terminal is enabled but aiohttp is unavailable; install requirements.txt to enable it.')
        return
    try:
        _token, token_source = _load_web_terminal_secret()

        @aiohttp_web.middleware
        async def _security_middleware(request, handler):
            remote = str(request.remote or '')
            try:
                remote_ip = ipaddress.ip_address(remote.split('%', 1)[0])
                if remote_ip.version == 6 and remote_ip.ipv4_mapped:
                    remote_ip = remote_ip.ipv4_mapped
                if not remote_ip.is_loopback:
                    return aiohttp_web.Response(status=403, text='Loopback access only')
            except ValueError:
                return aiohttp_web.Response(status=403, text='Loopback access only')
            from urllib.parse import urlparse
            host_header = str(request.headers.get('Host', '')).strip().lower()
            allowed_hosts = {'ssh.rgnodes.bond', 'ssh.rgnodes.bond:443', 'localhost', f'localhost:{WEB_TERMINAL_PORT}', '127.0.0.1', f'127.0.0.1:{WEB_TERMINAL_PORT}', '[::1]', f'[::1]:{WEB_TERMINAL_PORT}'}
            if host_header not in allowed_hosts:
                return aiohttp_web.Response(status=421, text='Host not allowed')
            origin = request.headers.get('Origin')
            if origin:
                parsed = urlparse(origin)
                origin_host = (parsed.hostname or '').lower()
                origin_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
                domain_origin = parsed.scheme == 'https' and origin_host == 'ssh.rgnodes.bond' and (origin_port == 443)
                local_origin = parsed.scheme == 'http' and origin_host in {'localhost', '127.0.0.1', '::1'} and (origin_port == WEB_TERMINAL_PORT)
                if not (domain_origin or local_origin):
                    return aiohttp_web.Response(status=403, text='Origin not allowed')
            response = await handler(request)
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Content-Security-Policy'] = f"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self' wss://ssh.rgnodes.bond ws://localhost:{WEB_TERMINAL_PORT} ws://127.0.0.1:{WEB_TERMINAL_PORT}; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            return response
        app = aiohttp_web.Application(middlewares=[_security_middleware], client_max_size=16384)
        app.router.add_get('/', _web_terminal_root)
        app.router.add_post('/api/login', _web_terminal_login)
        app.router.add_post('/api/logout', _web_terminal_logout)
        app.router.add_get('/ws', _web_terminal_websocket)
        runner = aiohttp_web.AppRunner(app, access_log=None, shutdown_timeout=3)
        await runner.setup()
        site = aiohttp_web.TCPSite(runner, '127.0.0.1', WEB_TERMINAL_PORT, reuse_address=True)
        await site.start()
        _WEB_TERMINAL_RUNNER = runner
        logger.info('AxionHost OpenSSH Terminal listening on loopback port %d; public endpoint %s requires HTTPS reverse proxy.', WEB_TERMINAL_PORT, WEB_TERMINAL_PUBLIC_URL)
        logger.info('Web terminal access token source: %s (token contents are never logged).', token_source)
    except Exception as exc:
        logger.error('AXIONHOST web terminal did not start (%s). The Discord bot will continue safely.', type(exc).__name__)
@bot.check
async def rgnodes_maintenance_command_gate(ctx):
    if not maintenance_enabled() or is_admin_user(getattr(ctx, 'author', None)):
        return True
    name = str(getattr(getattr(ctx, 'command', None), 'name', '') or '').lower()
    if name in MAINTENANCE_SAFE_COMMANDS:
        return True
    raise AXIONHOSTMaintenanceError()
@bot.event
async def on_guild_join(guild: discord.Guild):
    if AUTO_CREATE_SERVER_EMOJIS:
        try:
            await auto_provision_server_emojis(guild)
        except Exception as exc:
            logger.warning(f'Initial emoji provisioning failed for {guild.name}: {exc}')
class DeployTypeView(AXIONHOSTView):
    """Single-product deployment selector: AxionHost VPS on LXD/LXC."""

    def __init__(self, user: discord.Member, ctx, expiry_days: int=None):
        super().__init__(timeout=300)
        self.user = user
        self.ctx = ctx
        self.expiry_days = expiry_days if expiry_days and expiry_days > 0 else DEFAULT_VPS_EXPIRATION_DAYS
        self.select = discord.ui.Select(placeholder='Select VPS', options=[discord.SelectOption(label='VPS — LXD/LXC', value='VPS', description='Real LXD/LXC VPS • public IPv4 • automatic resource protection', emoji='🖥️')], row=0)
        self.select.callback = self.select_type
        self.add_item(self.select)

    async def select_type(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(embed=create_error_embed('Access Denied', 'Only the command author can use this deployment selector.'), ephemeral=True)
            return
        # Administrators intentionally have no bot-imposed VPS count limit.
        if (not is_admin_user_id(str(interaction.user.id))) and user_has_vps(self.user.id):
            await interaction.response.send_message(embed=create_error_embed('VPS Limit Reached', f'{self.user.mention} already has a VPS. Limit: 1.'), ephemeral=True)
            return
        self.select.disabled = True
        await interaction.response.edit_message(embed=create_info_embed('🖥️ AxionHost VPS Deployment', f'**Provider:** {HOST_PROVIDER_NAME}\n**Backend:** LXD/LXC\n**Network:** real public IPv4 when the node public network is configured\n**Default plan:** {DEFAULT_VPS_RAM_GB} GB RAM • {DEFAULT_VPS_CPU} CPU • {DEFAULT_VPS_STORAGE_GB} GB disk\n**Admin creation ceiling:** {MAX_VPS_RAM_GB} GB RAM • {MAX_VPS_CPU} CPU • {VPS_MAX_DISK_GB} GB disk\n\nHost capacity and reserved headroom are checked before deployment.'), view=NodeSelectView(DEFAULT_VPS_RAM_GB, DEFAULT_VPS_CPU, DEFAULT_VPS_STORAGE_GB, self.user, self.ctx, self.expiry_days, deploy_mode=True))
@bot.command(name='deploy-new')
async def deploy_command(ctx, user: discord.Member=None):
    """Interactive VPS deployment. LXD/LXC is the only virtualization backend."""
    target = user or ctx.author
    caller_is_admin = is_admin_user(ctx.author)
    if user is not None and (not caller_is_admin):
        await ctx.send(embed=create_error_embed('Access Denied', 'Only admins can deploy a VPS for another Discord account.'))
        return
    if maintenance_enabled() and (not caller_is_admin):
        await ctx.send(embed=create_warning_embed('🔶 Under Maintenance', 'VPS deployment is temporarily disabled while maintenance mode is enabled.'))
        return
    if (not caller_is_admin) and user_has_vps(target.id):
        await ctx.send(embed=create_error_embed('VPS Limit Reached', f'{target.mention} already has a VPS. This system allows 1 VPS per account.'))
        return
    network_state = 'ready' if PUBLIC_BRIDGE_NAME or PUBLIC_PARENT_INTERFACE or PUBLIC_IPV4_POOL_CIDR else 'requires public-node configuration'
    description = f'**Product:** AxionHost VPS\n**Virtualization:** LXD/LXC\n**Public IPv4:** {network_state}\n**Starting allocation:** {INITIAL_VPS_RAM_GB} GB RAM • {INITIAL_VPS_CPU} CPU • {INITIAL_VPS_DISK_GB} GB disk\n**Maximum limit:** {MAX_VPS_RAM_GB} GB RAM • {MAX_VPS_CPU} CPU • {MAX_VPS_DISK_GB} GB disk\n**Protection:** automatic SSH hardening, fail2ban, unattended security updates and host resource guards.\n\nSelect the VPS option to continue.'
    await ctx.send(embed=create_info_embed('🚀 AxionHost Deployment Center', description), view=DeployTypeView(target, ctx))
@is_admin()
async def create_machine(ctx, ram: int, cpu: int, disk: int, user: discord.Member, product: str='VPS', expiry_days: int=None):
    """Admin VPS creation: <ram> <cpu> <disk> @user [VPS] [expiry-days]. Only VPS exists."""
    if str(product or 'VPS').strip().upper() != 'VPS':
        await ctx.send(embed=create_error_embed('Invalid Product', f'Only `VPS` is supported. Usage: `{PREFIX}create <RAM> <CPU> <DISK> @user VPS [expiry-days]`.'))
        return
    try:
        ram, cpu, disk = (int(ram), int(cpu), int(disk))
    except (TypeError, ValueError):
        await ctx.send(embed=create_error_embed('Invalid Resources', 'RAM, CPU and Disk must be whole numbers.'))
        return
    if not (1 <= ram <= MAX_VPS_RAM_GB and 1 <= cpu <= MAX_VPS_CPU and (VPS_MIN_DISK_GB <= disk <= VPS_MAX_DISK_GB)):
        await ctx.send(embed=create_error_embed('Invalid Resources', f'Allowed limits: **RAM 1–{MAX_VPS_RAM_GB} GB** • **CPU 1–{MAX_VPS_CPU}** • **Disk {VPS_MIN_DISK_GB}–{VPS_MAX_DISK_GB} GB**.'))
        return
    # Admins may create any number of VPS for the same Discord account.
    if (not is_admin_user_id(str(ctx.author.id))) and user_has_vps(user.id):
        await ctx.send(embed=create_error_embed('VPS Limit Reached', f'{user.mention} already owns a VPS.'))
        return
    expiry = int(expiry_days) if expiry_days and int(expiry_days) > 0 else DEFAULT_VPS_EXPIRATION_DAYS
    description = f'**Owner:** {user.mention}\n**Backend:** LXD/LXC\n**Maximum:** {ram} GB RAM • {cpu} CPU • {disk} GB disk\n**Starting allocation:** {min(INITIAL_VPS_RAM_GB, ram)} GB RAM • {min(INITIAL_VPS_CPU, cpu)} CPU • {min(INITIAL_VPS_DISK_GB, disk)} GB disk\n**Expiry:** {expiry} days\n\nSelect a node and OS to continue.'
    await ctx.send(embed=create_info_embed('🖥️ VPS Creation', description))
    await ctx.channel.send(embed=create_info_embed('Choose Node', 'Select the LXD/LXC node where this VPS should be created.'), view=NodeSelectView(ram, cpu, disk, user, ctx, expiry))
class PortAddModal(discord.ui.Modal, title='🌐 Add Port Forward'):
    vps_port = discord.ui.TextInput(label='VPS Port', placeholder='25565', min_length=1, max_length=5, required=True)

    def __init__(self, owner_id: str, container_name: str, node_id: int):
        super().__init__(timeout=120)
        self.owner_id = str(owner_id)
        self.container_name = str(container_name)
        self.node_id = int(node_id)

    async def on_submit(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.owner_id and (not is_admin_user(interaction.user)):
            await interaction.response.send_message(embed=create_error_embed('Access Denied', 'You do not own this VPS.'), ephemeral=True)
            return
        try:
            port = int(str(self.vps_port.value).strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(embed=create_error_embed('Invalid Port', 'VPS port must be between 1 and 65535.'), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            host_port = await create_port_forward(self.owner_id, self.container_name, port, self.node_id)
            if not host_port:
                await interaction.followup.send(embed=create_error_embed('Port Creation Failed', 'No free port/quota is available, or the public-IP port configuration could not be created.'), ephemeral=True)
                return
            await interaction.followup.send(embed=create_success_embed('🌐 Port Forward Created', f'**VPS:** `{self.container_name}`\n**Guest/Public Port:** `{port}`\n**Protocol:** `TCP + UDP`\n\nThe VPS uses its own public IPv4; no host-NAT port is fabricated. Reachability also requires a listening service and provider routing/firewall to allow this port. Managed UFW rules are reconciled when UFW is active.'), ephemeral=True)
        except Exception as e:
            logger.error(f'Port modal failed for {self.container_name}: {e}', exc_info=True)
            await interaction.followup.send(embed=create_error_embed('Port Error', safe_error_summary('Port update', e)), ephemeral=True)
class PortsView(AXIONHOSTView):
    """Persistent port-forward control panel for one VPS."""

    def __init__(self, owner_id: str, container_name: str, node_id: int):
        super().__init__(timeout=300)
        self.owner_id = str(owner_id)
        self.container_name = str(container_name)
        self.node_id = int(node_id)
        self._rebuild_items()

    def _rebuild_items(self):
        self.clear_items()
        add_btn = discord.ui.Button(label='Add Port', emoji='➕', style=discord.ButtonStyle.secondary, row=0)
        add_btn.callback = self.add_port
        refresh_btn = discord.ui.Button(label='Refresh', emoji='🔄', style=discord.ButtonStyle.secondary, row=0)
        refresh_btn.callback = self.refresh
        close_btn = discord.ui.Button(label='Close', emoji='❌', style=discord.ButtonStyle.secondary, row=0)
        close_btn.callback = self.close
        self.add_item(add_btn)
        self.add_item(refresh_btn)
        self.add_item(close_btn)
        forwards = [f for f in get_user_forwards(self.owner_id) if str(f.get('vps_container')) == self.container_name]
        if forwards:
            options = [discord.SelectOption(label=f"Remove ID {f['id']}", description=f"Host {f['host_port']} → VPS {f['vps_port']} TCP/UDP", value=str(f['id'])) for f in forwards[:25]]
            select = discord.ui.Select(placeholder='🗑️ Select a forward to remove', options=options, row=1)
            select.callback = self.remove
            self.add_item(select)

    def _embed(self):
        forwards = [f for f in get_user_forwards(self.owner_id) if str(f.get('vps_container')) == self.container_name]
        quota = get_user_allocation(self.owner_id)
        lines = [f"• `{f['id']}` → host `{f['host_port']}` ⇢ VPS `{f['vps_port']}` • TCP/UDP" for f in forwards]
        body = f'**VPS:** `{self.container_name}`\n**Usage:** `{len(forwards)}/{quota}`\n\n' + ('\n'.join(lines) if lines else 'None configured') + '\n\nPublic port reservations are allocated automatically and persisted in the bot database.'
        return create_info_embed('🌐 Port Forwarding', body)

    async def add_port(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.owner_id and (not is_admin_user(interaction.user)):
            await interaction.response.send_message(embed=create_error_embed('Access Denied', 'You do not own this VPS.'), ephemeral=True)
            return
        await interaction.response.send_modal(PortAddModal(self.owner_id, self.container_name, self.node_id))

    async def remove(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.owner_id and (not is_admin_user(interaction.user)):
            await interaction.response.send_message(embed=create_error_embed('Access Denied', 'You do not own this VPS.'), ephemeral=True)
            return
        select = interaction.data.get('values', []) if isinstance(interaction.data, dict) else []
        if not select:
            await interaction.response.send_message(embed=create_error_embed('No Port Selected', 'Select a forwarding rule first.'), ephemeral=True)
            return
        try:
            fid = int(select[0])
        except ValueError:
            await interaction.response.send_message(embed=create_error_embed('Invalid Forward', 'The selected forwarding rule is invalid.'), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ok, owner = await remove_port_forward(fid, requester_id=str(interaction.user.id), is_admin=is_admin_user(interaction.user))
        await interaction.followup.send(embed=create_success_embed('🗑️ Port Removed', f'Forward ID `{fid}` was removed.') if ok else create_error_embed('Remove Failed', 'That forward does not exist, is not yours, or could not be fully removed.'), ephemeral=True)
        await self.refresh(interaction, from_followup=True)

    async def refresh(self, interaction: discord.Interaction, from_followup: bool=False):
        self._rebuild_items()
        try:
            if not from_followup and (not interaction.response.is_done()):
                await interaction.response.edit_message(embed=self._embed(), view=self)
            elif interaction.message:
                await interaction.message.edit(embed=self._embed(), view=self)
        except Exception as e:
            logger.debug(f'Port view refresh failed: {e}')

    async def close(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.owner_id and (not is_admin_user(interaction.user)):
            await interaction.response.send_message(embed=create_error_embed('Access Denied', 'You do not own this VPS.'), ephemeral=True)
            return
        await interaction.response.edit_message(view=None)
        self.stop()
@bot.command(name='permissions')
@is_admin()
async def permissions_check_command(ctx, channel: discord.TextChannel=None):
    """Audit the bot's effective Discord permissions in a target channel."""
    if ctx.guild is None:
        await ctx.send(embed=create_error_embed('Invalid Context', 'Use this command inside a Discord server.'))
        return
    target = channel or ctx.channel
    me = ctx.guild.me
    if me is None:
        await ctx.send(embed=create_error_embed('Permission Audit Failed', 'Discord has not provided the bot member object yet.'))
        return
    perms = target.permissions_for(me)
    required = {'View Channel': perms.view_channel, 'Send Messages': perms.send_messages, 'Embed Links': perms.embed_links, 'Attach Files': perms.attach_files, 'Read Message History': perms.read_message_history, 'Manage Messages': perms.manage_messages, 'Manage Channels': perms.manage_channels, 'Manage Roles': perms.manage_roles, 'Manage Webhooks': perms.manage_webhooks}
    lines = [f"{('✅' if ok else '❌')} **{name}**" for name, ok in required.items()]
    missing = [name for name, ok in required.items() if not ok]
    embed = create_info_embed('🛡️ AXIONHOST Permission Audit', f'Effective permissions for the bot in {target.mention}.')
    add_field(embed, 'Core Logging', '\n'.join(lines[:5]), False)
    add_field(embed, 'Management', '\n'.join(lines[5:]), False)
    add_field(embed, 'Result', '✅ Core permissions are available.' if not missing else f"⚠️ Missing: {', '.join(missing)}", False)
    await ctx.send(embed=embed)
@bot.group(name='update', invoke_without_command=True)
@commands.guild_only()
@is_admin()
async def update_group(ctx):
    await ctx.send(embed=create_info_embed('⚙️ Update Center', f'Use `{PREFIX}update logs #channel` to configure the VPS/node log channel.'))
@update_group.command(name='logs')
@is_admin()
async def update_logs(ctx, channel: discord.TextChannel):
    if ctx.guild is None or ctx.guild.me is None:
        await ctx.send(embed=create_error_embed('Invalid Context', 'Use this command inside a Discord server.'))
        return
    perms = channel.permissions_for(ctx.guild.me)
    missing = [name for name, ok in (('View Channel', perms.view_channel), ('Send Messages', perms.send_messages), ('Embed Links', perms.embed_links), ('Attach Files', perms.attach_files)) if not ok]
    if missing:
        await ctx.send(embed=create_error_embed('Permission Check Failed', f"I need: {', '.join(missing)} in {channel.mention}."))
        return
    set_audit_channel_id(channel.id)
    await record_audit_event('system', 'Logs Channel Updated', f'VPS + node logs are now published to {channel.mention}.', user_id=ctx.author.id, announce=False)
    await ctx.send(embed=create_success_embed('✅ Logs Channel Updated', f'VPS + node logs will now be sent to {channel.mention}.\n\nRequired bot permissions were verified: **View Channel • Send Messages • Embed Links**.'))
    try:
        await channel.send(embed=create_success_embed('📝 AXIONHOST Logging Active', 'VPS and node operational events will appear here.\n\n✅ VPS audit events\n✅ Node health snapshots\n✅ Detailed `log-vps` / `node-logs` snapshots\n✅ Secrets are redacted from command-audit text.'), allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass
@bot.command(name='update-logs')
@commands.guild_only()
@is_admin()
async def update_logs_alias(ctx, channel: discord.TextChannel):
    """Convenience alias for `update logs #channel`."""
    await update_logs.callback(ctx, channel)
@bot.command(name='log-channel')
@commands.guild_only()
@is_admin()
async def log_channel_command(ctx, action: str='show'):
    """Show or test the configured operational log channel."""
    action = str(action or 'show').lower().strip()
    channel_id = _audit_channel_id()
    if action in {'show', 'status'}:
        if not channel_id:
            await ctx.send(embed=create_warning_embed('📝 Logs Channel', f'No log channel is configured. Use `{PREFIX}update logs #channel`.'))
            return
        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            await ctx.send(embed=create_info_embed('📝 Logs Channel', f"Configured channel: {getattr(channel, 'mention', f'`{channel_id}`')}\n\nVPS + node event logging is active."))
        except Exception:
            await ctx.send(embed=create_warning_embed('📝 Logs Channel', f'Configured channel ID `{channel_id}` is not currently reachable. Use `{PREFIX}update logs #channel` to repair it.'))
        return
    if action in {'test', 'check'}:
        await logs_test_command.callback(ctx)
        return
    await ctx.send(embed=create_error_embed('Invalid Action', f'Use `{PREFIX}log-channel show` or `{PREFIX}log-channel test`.'))
@bot.group(name='add', invoke_without_command=True)
@commands.guild_only()
@is_admin()
async def add_group(ctx):
    await ctx.send(embed=create_info_embed('➕ Admin Add', f'Use `{PREFIX}add slots @user amount`.'))
@add_group.command(name='slots')
@is_admin()
async def add_group_slots(ctx, user: discord.Member, amount: int):
    if amount <= 0 or amount > 1000:
        await ctx.send(embed=create_error_embed('Invalid Amount', 'Slots must be between 1 and 1000.'))
        return
    before = get_user_allocation(str(user.id))
    allocate_ports(str(user.id), amount)
    after = get_user_allocation(str(user.id))
    await record_audit_event('vps', 'Port Slots Added', f'Allocated `{amount}` slots. Quota `{before}` → `{after}`.', user_id=ctx.author.id)
    await ctx.send(embed=create_success_embed('✅ Slots Added', f'Added **{amount}** port-forwarding slots to {user.mention}.\n**New quota:** `{after}`'))
    try:
        await user.send(embed=create_info_embed('🌐 Port Slots Updated', f'An administrator added **{amount}** port-forwarding slots to your account.\n**New quota:** `{after}`'))
    except discord.Forbidden:
        pass
@bot.command(name='add-slots')
@commands.guild_only()
@is_admin()
async def add_slots_alias(ctx, user: discord.Member, amount: int):
    """Convenience alias for `add slots @user amount`."""
    await add_group_slots.callback(ctx, user, amount)
async def slots_command(ctx, user: discord.Member=None):
    """Show a user's port-slot quota. Admins may inspect another user."""
    if user is not None and str(user.id) != str(ctx.author.id) and (not is_admin_user(ctx.author)):
        await ctx.send(embed=create_error_embed('Access Denied', 'You can only inspect your own slot quota unless you are an administrator.'))
        return
    target = user or ctx.author
    allocated = get_user_allocation(str(target.id))
    used = get_user_used_ports(str(target.id))
    available = max(0, allocated - used)
    embed = create_info_embed('🌐 Port Slot Quota', f'Slot allocation for {target.mention}.')
    add_field(embed, 'Allocated', f'`{allocated}` slots', True)
    add_field(embed, 'Used', f'`{used}` slots', True)
    add_field(embed, 'Available', f'`{available}` slots', True)
    await ctx.send(embed=embed)
@bot.command(name='log-vps')
async def log_vps_command(ctx, container_name: str, lines: int=LOG_CHANNEL_SNAPSHOT_LINES):
    """Fetch VPS guest logs and mirror the result to the configured log channel."""
    await vps_logs.callback(ctx, container_name, lines)
@bot.command(name='log-node')
@is_admin()
async def log_node_command(ctx, node_id: int, limit: int=LOG_CHANNEL_SNAPSHOT_LINES):
    """Fetch node diagnostics and mirror the result to the configured log channel."""
    await node_logs_command.callback(ctx, node_id, limit)
@bot.command(name='logs-test')
@commands.guild_only()
@is_admin()
async def logs_test_command(ctx):
    """Verify the configured log channel and permissions without changing anything."""
    channel_id = _audit_channel_id()
    if not channel_id:
        await ctx.send(embed=create_warning_embed('📝 Logs Not Configured', f'Use `{PREFIX}update logs #channel` first.'))
        return
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        if ctx.guild and isinstance(channel, discord.TextChannel) and ctx.guild.me:
            perms = channel.permissions_for(ctx.guild.me)
            missing = [name for name, ok in (('View Channel', perms.view_channel), ('Send Messages', perms.send_messages), ('Embed Links', perms.embed_links)) if not ok]
            if missing:
                await ctx.send(embed=create_error_embed('Permission Check Failed', f"Missing in {channel.mention}: {', '.join(missing)}"))
                return
        probe = create_success_embed('🧪 AXIONHOST Logs Test', f"Log delivery is working for {getattr(channel, 'mention', channel_id)}.")
        await channel.send(embed=probe, allowed_mentions=discord.AllowedMentions.none())
        await ctx.send(embed=create_success_embed('✅ Logs Channel Healthy', f"A test event was delivered to {getattr(channel, 'mention', f'`{channel_id}`')}."))
    except Exception as exc:
        await ctx.send(embed=create_error_embed('❌ Logs Test Failed', safe_error_summary('Logs test', exc)))
@bot.command(name='bandwidth')
async def bandwidth_command(ctx, vps_ref: str=None):
    target = vps_ref
    if target:
        owner_id, _, vps = find_vps_record(target)
    else:
        owner_id = str(ctx.author.id)
        items = vps_data.get(owner_id, [])
        vps = items[0] if len(items) == 1 else None
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'Use `{PREFIX}bandwidth <vps-id|container>` as an administrator, or own exactly one VPS.'))
        return
    if str(ctx.author.id) != str(owner_id) and (not is_admin_user(ctx.author)):
        await ctx.send(embed=create_error_embed('Access Denied', 'You can only view your own VPS bandwidth unless you are an administrator.'))
        return
    rx, tx = await get_container_network_usage(str(vps.get('container_name')), int(vps.get('node_id', 1)))
    embed = create_info_embed('🌐 VPS Bandwidth', f"`{vps.get('container_name')}` • **AXIONHOST fixed 50GB/month plan**")
    quota_gb = VPS_BANDWIDTH_GB
    used_bytes = int(vps.get('bandwidth_used_bytes') or 0)
    used_gb = used_bytes / 1024 ** 3
    remaining_gb = max(0.0, quota_gb - used_gb)
    add_field(embed, 'Monthly Quota', f'**{quota_gb} GB**', True)
    add_field(embed, 'Accounted Usage', f'**{used_gb:.2f} GB**', True)
    add_field(embed, 'Remaining', f'**{remaining_gb:.2f} GB**', True)
    add_field(embed, 'Live RX / TX', f'RX `{rx}` • TX `{tx}`', False)
    add_field(embed, 'Cycle', f"`{str(vps.get('bandwidth_cycle_start') or 'current')[:19]}`", True)
    await ctx.send(embed=embed)
@is_admin()
async def node_capacity_command(ctx, node_id: int=1):
    """Low-overhead host capacity snapshot used before provisioning."""
    node = get_node(node_id)
    if not node:
        await ctx.send(embed=create_error_embed('Node Not Found', f'Node `{node_id}` was not found.'))
        return
    try:
        stats = await asyncio.wait_for(get_host_stats(node_id), timeout=12)
        total_ram = int(stats.get('ram_bytes_total') or 0)
        available_ram = int(stats.get('ram_bytes_available') or 0)
        used_ram = max(0, total_ram - available_ram)
        disk = stats.get('disk') or {}
        cpu = float(stats.get('cpu') or 0.0)
        ram_pct = used_ram / total_ram * 100.0 if total_ram else float(stats.get('ram') or 0.0)
        disk_pct = float(disk.get('percent', 0) or 0) if isinstance(disk, dict) else 0.0
        embed = create_info_embed('🧠 Node Capacity', f"**{node.get('name', 'Node')}** • `{node_id}`\nProvider: **{HOST_PROVIDER_NAME}** • CPU: **{HOST_PROCESSOR_NAME}**")
        add_field(embed, 'CPU', f'`{cpu:.1f}%` used • deploy ceiling `{HOST_CPU_MAX_DEPLOY_PCT:.0f}%`', True)
        add_field(embed, 'RAM', f'`{available_ram / 1024 ** 3:.2f} GiB` free / `{total_ram / 1024 ** 3:.2f} GiB` total • `{ram_pct:.1f}%` used', True)
        add_field(embed, 'Disk', f'`{disk_pct:.1f}%` used • reserve `{HOST_DISK_RESERVE_GB:.1f} GiB`', True)
        add_field(embed, 'Allocation Policy', f"RAM share ≤ `{MAX_DEPLOY_RAM_SHARE * 100:.0f}%` • RAM reserve `{HOST_RAM_RESERVE_GB:.1f} GiB` • swap guests `{('ON' if VPS_SWAP_ENABLED else 'OFF')}`", False)
        await ctx.send(embed=embed)
    except Exception as exc:
        await ctx.send(embed=create_error_embed('Node Capacity Failed', safe_error_summary('Node capacity check', exc)))
@bot.command(name='node-logs')
@commands.guild_only()
@is_admin()
async def node_logs_command(ctx, node_id: int, limit: int=25):
    """Admin node diagnostics, local LXD journal (when available), and audit snapshots."""
    limit = max(5, min(50, int(limit)))
    node = get_node(node_id)
    if not node:
        await ctx.send(embed=create_error_embed('Node Not Found', f'Node `{node_id}` was not found.'))
        return
    await ctx.send(embed=create_info_embed('🧩 Gathering Node Logs', f"Checking `{node.get('name', 'Node')}`..."))
    try:
        stats = await asyncio.wait_for(get_host_stats(node_id), timeout=12)
        cpu = float(stats.get('cpu') or 0)
        ram = float(stats.get('ram') or 0)
        disk = stats.get('disk') or {}
        if isinstance(disk, dict):
            disk_text = f"{float(disk.get('percent', 0) or 0):.1f}% used • {int(disk.get('free', 0) or 0) / 1024 ** 3:.1f} GiB free"
        else:
            disk_text = str(disk)
        health = f'CPU `{cpu:.1f}%` • RAM `{ram:.1f}%` • Disk `{disk_text}`'
    except Exception as exc:
        health = safe_error_summary('Node health check', exc)
    journal = 'Remote node journal unavailable through the current node-agent contract.'
    if node.get('is_local'):
        try:

            def _read_local_node_journal() -> str:
                proc = subprocess.run(['journalctl', '--no-pager', '-n', str(min(limit, 50)), '-u', 'libvirtd.service', '-u', 'virtqemud.service'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=12, check=False)
                return proc.stdout or 'No local libvirt service journal entries.'
            journal = await asyncio.to_thread(_read_local_node_journal)
        except Exception as exc:
            journal = safe_error_summary('Local node journal retrieval', exc)
    rows = get_recent_audit_logs(limit, node_id=node_id)
    lines_text = '\n'.join((f"{r.get('created_at', '')[:19]} | {r.get('kind', 'system')} | {r.get('action', 'Event')} | {r.get('detail', '')}" for r in rows)) or 'No node audit events recorded yet.'
    embed = create_info_embed('🧩 Node Logs', f"**{node.get('name', 'Node')}** • Node `{node_id}`\n{health}")
    add_field(embed, 'Node Service Logs', f'```text\n{journal[-2400:]}\n```', False)
    add_field(embed, 'Recent AXIONHOST Events', f'```text\n{lines_text[-2600:]}\n```', False)
    await ctx.send(embed=embed)
    channel_id = _audit_channel_id()
    if channel_id and (not getattr(ctx.channel, 'id', None) or int(ctx.channel.id) != int(channel_id)):
        try:
            target = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            raw_bundle = f"AXIONHOST NODE LOG SNAPSHOT\nNode: {node.get('name', 'Node')}\nNode ID: {node_id}\nGenerated: {datetime.now().isoformat()}\nHealth: {health}\n\n=== NODE SERVICE LOGS ===\n{journal}\n\n=== AXIONHOST AUDIT ===\n{lines_text}\n"
            if hasattr(target, 'send'):
                await _publish_log_bundle(target, embed, raw_bundle, f'node-{node_id}-logs.txt')
        except Exception as exc:
            logger.debug('Failed to publish node diagnostics to log channel: %s', exc)
    await record_audit_event('node', 'Node Logs Viewed', f'Diagnostic snapshot requested ({limit} events).', user_id=ctx.author.id, node_id=node_id)
@commands.guild_only()
@is_admin()
async def logs_command(ctx, limit: int=25):
    rows = get_recent_audit_logs(limit)
    lines = '\n'.join((f"`{str(r.get('created_at', ''))[:19]}` • **{r.get('kind', 'system').upper()} / {r.get('action', 'Event')}** — {r.get('detail', '')}" for r in rows[:25])) or 'No audit events recorded yet.'
    channel_id = _audit_channel_id()
    await ctx.send(embed=create_info_embed('📝 AXIONHOST Audit Logs', f"Configured channel: `{channel_id or 'Not configured'}`\n\n{lines[:3800]}"))
@bot.command(name='log-config')
@is_admin()
async def log_config_command(ctx):
    channel_id = _audit_channel_id()
    channel = bot.get_channel(channel_id) if channel_id else None
    label = channel.mention if channel else f'`{channel_id}`' if channel_id else 'Not configured'
    await ctx.send(embed=create_info_embed('📝 Log Channel', f'VPS + node operational logs are sent to: **{label}**\nUse `{PREFIX}update logs #channel` to change it.\n\nAutomatic: VPS actions + node health. Detailed: `{PREFIX}log-vps <vps>` / `{PREFIX}log-node <node>`.'))
@bot.command(name='node-log')
@is_admin()
async def node_log_alias(ctx, node_id: int, limit: int=25):
    await node_logs_command.callback(ctx, node_id, limit)
@bot.command(name='vps-log')
async def vps_log_alias(ctx, container_name: str, lines: int=50):
    owner_id, _, vps = find_vps_record(container_name)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'`{container_name}` was not found.'))
        return
    if str(ctx.author.id) != str(owner_id) and (not is_admin_user(ctx.author)):
        await ctx.send(embed=create_error_embed('Access Denied', 'You can only view logs for your own VPS.'))
        return
    await vps_logs.callback(ctx, container_name, lines)
@bot.command(name='motd')
@commands.guild_only()
@is_admin()
async def motd_command(ctx, action: str='show', *, text: str=''):
    action = str(action or 'show').lower().strip()
    if action == 'show':
        current = get_motd_text()
        status = '🟢 Enabled' if current else '⚪ Disabled'
        body = current or 'MOTD is currently disabled.'
        await ctx.send(embed=create_info_embed('📜 Current MOTD', f'**Status:** {status}\n\n```text\n{body[:1800]}\n```'))
        return
    if action in {'clear', 'off', 'disable'}:
        set_setting('motd_text', '')
        ok, failed = await apply_motd_to_all_running_vps()
        await record_audit_event('system', 'MOTD Disabled', f'Cleared on `{ok}` running VPS; `{failed}` failed.', user_id=ctx.author.id)
        await ctx.send(embed=create_success_embed('✅ MOTD Disabled', f'Cleared on **{ok}** running VPS. Failed: **{failed}**.'))
        return
    if action in {'set', 'on', 'enable'}:
        text = text.strip()[:1200]
        if not text:
            await ctx.send(embed=create_error_embed('Missing MOTD', f'Usage: `{PREFIX}motd set Your message here`'))
            return
        set_setting('motd_text', text)
        await ctx.send(embed=create_info_embed('📜 Applying MOTD', 'Saving the new MOTD and applying it to running VPS...'))
        ok, failed = await apply_motd_to_all_running_vps()
        await record_audit_event('system', 'MOTD Updated', f'Applied to `{ok}` running VPS; `{failed}` failed.', user_id=ctx.author.id)
        await ctx.send(embed=create_success_embed('✅ MOTD Updated', f'Applied to **{ok}** running VPS. Failed: **{failed}**.'))
        return
    await ctx.send(embed=create_error_embed('Invalid MOTD Action', f'Use `{PREFIX}motd show`, `{PREFIX}motd set <text>`, or `{PREFIX}motd clear`.'))
@bot.command(name='add-admin')
@is_main_admin()
async def add_admin_alias(ctx, user: discord.Member):
    """Stable alias requested by operators for adding an admin."""
    await admin_add.callback(ctx, user)
def _dashboard_valid_global_ipv4(value: str) -> bool:
    try:
        import ipaddress
        ip = ipaddress.ip_address(str(value or '').strip())
        return bool(ip.version == 4 and ip.is_global and (not ip.is_multicast) and (not ip.is_reserved) and (not ip.is_unspecified) and (not ip.is_loopback) and (not ip.is_link_local))
    except Exception:
        return False
def _collect_dashboard_host_metrics() -> Dict[str, Any]:
    """Collect local host metrics in a worker thread; never block the Discord event loop."""
    result: Dict[str, Any] = {'cpu': None, 'ram_pct': None, 'ram_used_gb': None, 'ram_total_gb': None, 'disk_pct': None, 'disk_used_gb': None, 'disk_total_gb': None, 'uptime_seconds': None, 'load1': None, 'cpu_count': os.cpu_count() or 0, 'net_rx_mb': None, 'net_tx_mb': None, 'interfaces_up': []}
    try:
        import psutil
        result['cpu'] = float(psutil.cpu_percent(interval=0.2))
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        result.update({'ram_pct': float(memory.percent), 'ram_used_gb': memory.used / 1024 ** 3, 'ram_total_gb': memory.total / 1024 ** 3, 'disk_pct': float(disk.percent), 'disk_used_gb': disk.used / 1024 ** 3, 'disk_total_gb': disk.total / 1024 ** 3, 'uptime_seconds': max(0.0, time.time() - float(psutil.boot_time()))})
        counters = psutil.net_io_counters()
        if counters:
            result['net_rx_mb'] = counters.bytes_recv / 1024 ** 2
            result['net_tx_mb'] = counters.bytes_sent / 1024 ** 2
        result['interfaces_up'] = sorted((name for name, stats in psutil.net_if_stats().items() if stats.isup and name != 'lo'))
    except Exception as exc:
        logger.debug('Dashboard psutil metrics unavailable: %s', type(exc).__name__)
    try:
        loads = os.getloadavg()
        result['load1'] = float(loads[0])
    except (AttributeError, OSError):
        pass
    return result
def _dashboard_probe_command(argv: List[str], timeout: float=2.5) -> tuple[bool, str]:
    """Run a fixed diagnostic argv (never user-supplied shell text)."""
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        text = (completed.stdout or completed.stderr or '').strip()
        return (completed.returncode == 0, text[:500])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (False, type(exc).__name__)
def _collect_dashboard_services() -> Dict[str, Any]:
    """Read-only LXD/Docker/firewall service probes; this function never changes host policy."""
    kvm_device = bool(shutil.which('lxc'))
    virsh = shutil.which('lxc')
    libvirt_ok = False
    libvirt_detail = 'LXD CLI not installed' if not virsh else 'LXD daemon unavailable'
    if virsh:
        libvirt_ok, libvirt_detail = _dashboard_probe_command([virsh, 'info'], 3.0)
        if libvirt_ok:
            libvirt_detail = 'LXD daemon responding'
    docker = shutil.which('docker')
    docker_ok = False
    docker_detail = 'not installed' if not docker else 'daemon unavailable'
    if docker:
        docker_ok, docker_detail = _dashboard_probe_command([docker, 'info', '--format', '{{.ServerVersion}}'], 2.5)
        if docker_ok:
            docker_detail = 'daemon online · ' + (docker_detail or 'version unknown')
    ufw = shutil.which('ufw')
    ufw_state = 'not installed'
    if ufw:
        ok, text = _dashboard_probe_command([ufw, 'status'], 2.0)
        lowered = text.lower()
        if 'status: active' in lowered:
            ufw_state = 'active'
        elif 'status: inactive' in lowered:
            ufw_state = 'inactive'
        elif not ok:
            ufw_state = 'unknown'
    fail2ban_state = 'unknown'
    systemctl = shutil.which('systemctl')
    if systemctl:
        active, _ = _dashboard_probe_command([systemctl, 'is-active', 'fail2ban'], 2.0)
        if active:
            fail2ban_client = shutil.which('fail2ban-client')
            jail_ok, _ = _dashboard_probe_command([fail2ban_client, 'status', 'sshd'], 2.0) if fail2ban_client else (False, '')
            fail2ban_state = 'active · sshd jail active' if jail_ok else 'service active · sshd jail unverified'
        else:
            installed, _ = _dashboard_probe_command([systemctl, 'list-unit-files', 'fail2ban.service', '--no-legend'], 2.0)
            fail2ban_state = 'inactive/not installed' if installed else 'unknown'
    uplink = PUBLIC_PARENT_INTERFACE
    if not uplink:
        ip_cmd = shutil.which('ip')
        if ip_cmd:
            _, route = _dashboard_probe_command([ip_cmd, 'route', 'get', '1.1.1.1'], 1.5)
            match = re.search('\\bdev\\s+([A-Za-z0-9_.:@-]+)', route)
            if match:
                uplink = match.group(1)
    return {'kvm_device': kvm_device, 'libvirt_ok': libvirt_ok, 'libvirt_detail': libvirt_detail, 'virsh_available': bool(virsh), 'qemu_img_available': bool(libvirt_ok), 'docker_ok': docker_ok, 'docker_detail': docker_detail, 'ufw_state': ufw_state, 'fail2ban_state': fail2ban_state, 'uplink': uplink or 'not detected', 'bridge': PUBLIC_BRIDGE_NAME or 'not configured', 'network_mode': KVM_NETWORK_MODE}
async def _dashboard_public_ipv4() -> tuple[str, str]:
    """Return configured/detected host egress IPv4; explicitly not a guest-address guarantee."""
    configured = str(PUBLIC_IPV4 or '').strip()
    if _dashboard_valid_global_ipv4(configured):
        return (configured, 'configured')
    if not AUTO_DETECT_PUBLIC_IP:
        return ('', 'auto-detection disabled')
    now = time.monotonic()
    async with _DASHBOARD_PUBLIC_IP_LOCK:
        if now - float(_DASHBOARD_PUBLIC_IP_CACHE.get('checked_at', 0.0)) < 300:
            return (str(_DASHBOARD_PUBLIC_IP_CACHE.get('value', '')), str(_DASHBOARD_PUBLIC_IP_CACHE.get('source', 'cached')))
        value, source = ('', 'unavailable')
        try:
            response = await asyncio.wait_for(asyncio.to_thread(requests.get, 'https://api4.ipify.org', headers={'User-Agent': _make_discord_user_agent(BOT_NAME, BOT_VERSION)}, timeout=2.5), timeout=3.0)
            candidate = response.text.strip() if response.status_code == 200 else ''
            if _dashboard_valid_global_ipv4(candidate):
                value, source = (candidate, 'auto-detected host egress')
        except Exception as exc:
            logger.debug('Dashboard public IPv4 detection unavailable: %s', type(exc).__name__)
        _DASHBOARD_PUBLIC_IP_CACHE.update({'checked_at': time.monotonic(), 'value': value, 'source': source})
        return (value, source)
def _dashboard_progress(value: Optional[float]) -> str:
    if value is None:
        return '`unavailable`'
    try:
        numeric = max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return '`unavailable`'
    return create_progress_bar(numeric)
def _dashboard_uptime(seconds: Optional[float]) -> str:
    if seconds is None:
        return 'unavailable'
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f'{days}d {hours:02d}h {minutes:02d}m'
async def build_monitoring_dashboard_embed(frame: int=0) -> discord.Embed:
    """Create a detailed, animated-by-refresh AXIONHOST host + virtualisation dashboard."""
    metrics, services = await asyncio.gather(asyncio.to_thread(_collect_dashboard_host_metrics), asyncio.to_thread(_collect_dashboard_services))
    nodes = []
    try:
        nodes = list(get_nodes())
    except Exception as exc:
        logger.debug('Dashboard node inventory failed: %s', type(exc).__name__)
    vps_items = [v for owner_items in list(vps_data.values()) for v in list(owner_items)]
    total_vps = len(vps_items)
    running_vps = sum((1 for v in vps_items if str(v.get('status', '')).lower() == 'running' and (not v.get('suspended', False))))
    suspended_vps = sum((1 for v in vps_items if bool(v.get('suspended', False))))
    stopped_vps = max(0, total_vps - running_vps - suspended_vps)
    total_users = len(vps_data)

    async def check_node(node: Dict[str, Any]) -> bool:
        if node.get('is_local'):
            return bool(services['kvm_device'] and services['libvirt_ok'])
        url = str(node.get('url') or '').rstrip('/') + '/api/ping'
        key = str(node.get('api_key') or '')
        if not url.startswith(('https://', 'http://')) or not key:
            return False
        try:
            response = await asyncio.wait_for(asyncio.to_thread(requests.get, url, headers={'X-API-Key': key, 'User-Agent': _make_discord_user_agent(BOT_NAME, BOT_VERSION)}, timeout=2.5), timeout=3.0)
            return response.status_code == 200
        except Exception:
            return False
    node_checks = await asyncio.gather(*(check_node(n) for n in nodes[:20]), return_exceptions=True) if nodes else []
    nodes_checked = len(node_checks)
    nodes_online = sum((1 for result in node_checks if result is True))
    total_vps_users = sum((1 for _owner, items in vps_data.items() if items))
    public_ip, public_ip_source = await _dashboard_public_ipv4()
    cpu = metrics.get('cpu')
    ram = metrics.get('ram_pct')
    disk = metrics.get('disk_pct')
    health_issues = []
    if not services['kvm_device']:
        health_issues.append('LXD CLI unavailable')
    if not services['libvirt_ok']:
        health_issues.append('LXD daemon unavailable')
    if cpu is not None and cpu >= 90:
        health_issues.append('CPU critical')
    if ram is not None and ram >= 90:
        health_issues.append('RAM critical')
    if disk is not None and disk >= 95:
        health_issues.append('disk nearly full')
    if services['fail2ban_state'] != 'active · sshd jail active':
        health_issues.append('fail2ban not confirmed active')
    if not health_issues:
        health = '● ALL CHECKED SYSTEMS HEALTHY'
    elif any((x in health_issues for x in ('LXD CLI unavailable', 'LXD daemon unavailable', 'CPU critical', 'RAM critical', 'disk nearly full'))):
        health = '▲ ATTENTION REQUIRED · ' + ', '.join(health_issues[:3])
    else:
        health = '◆ PARTIAL HARDENING · ' + ', '.join(health_issues[:3])
    spinner = _DASHBOARD_FRAMES[frame % len(_DASHBOARD_FRAMES)]
    embed = create_embed(f'{spinner} AxionHost · LIVE HOST DASHBOARD', 'Animated monitoring panel · refreshes every 15 seconds while auto-refresh is enabled')
    embed.set_author(name='Power By AxionHost', icon_url=BOT_ICON_URL or None)
    load_text = f"{metrics['load1']:.2f}" if metrics.get('load1') is not None else 'unavailable'
    telemetry = f"**CPU**  {_dashboard_progress(cpu)}\n**RAM**  {_dashboard_progress(ram)}\n**Disk** {_dashboard_progress(disk)}\n**Uptime:** `{_dashboard_uptime(metrics.get('uptime_seconds'))}`\n**Load 1m:** `{load_text}`"
    add_field(embed, '⚡ Host Resource Telemetry', telemetry, True)
    ram_text = f"{metrics['ram_used_gb']:.2f}/{metrics['ram_total_gb']:.2f} GiB" if metrics.get('ram_used_gb') is not None and metrics.get('ram_total_gb') else 'unavailable'
    disk_text = f"{metrics['disk_used_gb']:.1f}/{metrics['disk_total_gb']:.1f} GiB" if metrics.get('disk_used_gb') is not None and metrics.get('disk_total_gb') else 'unavailable'
    network_text = f"RX `{metrics['net_rx_mb']:.1f} MiB` · TX `{metrics['net_tx_mb']:.1f} MiB`" if metrics.get('net_rx_mb') is not None and metrics.get('net_tx_mb') is not None else 'Counters unavailable'
    add_field(embed, '📦 Capacity', f"RAM `{ram_text}`\nDisk `{disk_text}`\nLogical CPUs `{metrics.get('cpu_count', 0)}`\n{network_text}", True)
    libvirt_status = 'ONLINE' if services['libvirt_ok'] else 'OFFLINE / UNAVAILABLE'
    kvm_status = 'PRESENT' if services['kvm_device'] else 'MISSING'
    docker_status = services['docker_detail'] if services['docker_ok'] else services['docker_detail']
    add_field(embed, '🧩 Virtualization & Docker', f'**LXD:** `{kvm_status}`\n**LXD daemon:** `{libvirt_status}`\n**Docker:** `{truncate_text(docker_status, 110)}`\n**Backend:** `LXD/LXC`', True)
    add_field(embed, '🌐 Network & Addressing', f"**Host egress IPv4:** `{public_ip or 'Unavailable'}`\n**Source:** `{public_ip_source}`\n**Mode:** `{services['network_mode']}`\n**Uplink:** `{services['uplink']}`\n**Bridge:** `{services['bridge']}`\n**Pool:** `{PUBLIC_IPV4_POOL_CIDR or 'not configured'}`", True)
    add_field(embed, '🛡️ Host Protection Signals', f"**Anti-mining policy:** `{('ENABLED' if ANTI_MINING_ENABLED else 'disabled')}`\n**Host CPU deploy ceiling:** `{HOST_CPU_MAX_DEPLOY_PCT:.0f}%`\n**RAM reserve:** `{HOST_RAM_RESERVE_GB:.1f} GiB`\n**Disk reserve:** `{HOST_DISK_RESERVE_GB:.1f} GiB`\n**Fail2ban:** `{services['fail2ban_state']}`\n**UFW:** `{services['ufw_state']}`", True)
    add_field(embed, '🖥️ VPS / Node Fleet', f'**VPS:** `{total_vps}` total · `{running_vps}` running · `{stopped_vps}` stopped · `{suspended_vps}` suspended\n**Owners with VPS:** `{total_vps_users}`\n**Nodes online:** `{nodes_online}/{nodes_checked}` checked' + (f' · `{max(0, len(nodes) - nodes_checked)}` beyond probe cap' if len(nodes) > nodes_checked else ''), True)
    latency = round(bot.latency * 1000) if bot.is_ready() and bot.latency is not None else None
    embed.add_field(name='➤ Bot / Health', value=(f"**Gateway:** `{('CONNECTED' if bot.is_ready() else 'NOT READY')}`\n**Latency:** `{latency} ms`" if latency is not None else f"**Gateway:** `{('CONNECTED' if bot.is_ready() else 'NOT READY')}`\n**Latency:** `unavailable`") + f'\n**Health:** {health}', inline=False)
    embed.set_footer(text=f"Power By AxionHost · Live frame {frame % len(_DASHBOARD_FRAMES) + 1}/{len(_DASHBOARD_FRAMES)} · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return embed
class MonitoringDashboardView(AXIONHOSTView):
    """Owner-controlled dashboard controls with bounded 5-minute auto-refresh."""

    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = int(owner_id)
        self.message = None
        self.auto_refresh = True
        self.frame = 0
        self._refresh_task = None

    async def _authorized(self, interaction: discord.Interaction) -> bool:
        if int(getattr(interaction.user, 'id', 0)) == self.owner_id or is_admin_user(interaction.user):
            return True
        await interaction.response.send_message('Only the dashboard creator or an administrator can control this live panel.', ephemeral=True)
        return False

    async def _render_and_edit(self, interaction: Optional[discord.Interaction]=None):
        self.frame = (self.frame + 1) % len(_DASHBOARD_FRAMES)
        embed = await build_monitoring_dashboard_embed(self.frame)
        if interaction is not None and (not interaction.response.is_done()):
            await interaction.response.edit_message(embed=embed, view=self)
        elif self.message is not None:
            await self.message.edit(embed=embed, view=self)

    def start_auto_refresh(self):
        if self.auto_refresh and (self._refresh_task is None or self._refresh_task.done()):
            self._refresh_task = asyncio.create_task(self._auto_refresh_loop(), name=f'rgnodes_dashboard_{self.owner_id}')

    async def _auto_refresh_loop(self):
        try:
            while self.auto_refresh and (not self.is_finished()):
                await asyncio.sleep(15)
                if not self.auto_refresh or self.is_finished() or self.message is None:
                    break
                try:
                    await self._render_and_edit()
                except discord.NotFound:
                    break
                except discord.HTTPException as exc:
                    logger.debug('Dashboard auto-refresh HTTP error: %s', getattr(exc, 'status', 'unknown'))
                except Exception as exc:
                    logger.warning('Dashboard auto-refresh failed (%s).', type(exc).__name__)
        except asyncio.CancelledError:
            raise
        finally:
            self._refresh_task = None

    @discord.ui.button(label='Refresh now', emoji='🔄', style=discord.ButtonStyle.secondary)
    async def refresh_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorized(interaction):
            return
        await interaction.response.defer()
        try:
            await self._render_and_edit()
        except Exception as exc:
            logger.warning('Manual dashboard refresh failed (%s).', type(exc).__name__)
            await interaction.followup.send('Dashboard refresh failed temporarily. Check bot logs and try again.', ephemeral=True)

    @discord.ui.button(label='Auto-refresh: ON', emoji='⏱️', style=discord.ButtonStyle.secondary)
    async def toggle_auto_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorized(interaction):
            return
        self.auto_refresh = not self.auto_refresh
        button.label = f"Auto-refresh: {('ON' if self.auto_refresh else 'OFF')}"
        button.style = discord.ButtonStyle.secondary if self.auto_refresh else discord.ButtonStyle.secondary
        if self.auto_refresh:
            self.start_auto_refresh()
        elif self._refresh_task and (not self._refresh_task.done()):
            self._refresh_task.cancel()
        await interaction.response.defer()
        await self._render_and_edit()

    @discord.ui.button(label='Close panel', emoji='✖️', style=discord.ButtonStyle.secondary)
    async def close_dashboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorized(interaction):
            return
        self.auto_refresh = False
        if self._refresh_task and (not self._refresh_task.done()):
            self._refresh_task.cancel()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content='AXIONHOST live dashboard session closed.', embed=None, view=self)
        self.stop()

    async def on_timeout(self):
        self.auto_refresh = False
        if self._refresh_task and (not self._refresh_task.done()):
            self._refresh_task.cancel()
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass
@bot.command(name='dashboard', aliases=['monitor', 'monitoring'])
@is_admin()
async def monitoring_dashboard(ctx):
    """Open a live host/LXD/IPv4/Docker/security monitor with animated refresh controls."""
    view = MonitoringDashboardView(ctx.author.id)
    try:
        embed = await build_monitoring_dashboard_embed(view.frame)
        message = await ctx.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        view.message = message
        view.start_auto_refresh()
    except Exception as exc:
        logger.error('Unable to render monitoring dashboard (%s).', type(exc).__name__, exc_info=True)
        await ctx.send(embed=create_error_embed('Dashboard Unavailable', 'Live metrics could not be collected. Check `-check` output and bot logs; no host settings were changed.'))
@bot.command(name='kvm-status', aliases=['kvmstatus', 'kvm-health'])
@is_admin()
async def kvm_status(ctx, node_id: int=None):
    """Show real LXD/LXC host health without disclosing node secrets."""
    try:
        selected_node = int(node_id) if node_id is not None else _preferred_deployment_node_id()
        node = get_node(selected_node)
        if not node:
            await ctx.send(embed=create_error_embed('LXD Status', f'Node `{selected_node}` is not configured.'))
            return
        health = await asyncio.wait_for(execute_vpsctl_compat('', 'health', node_id=selected_node, timeout=30), timeout=32)
        if not isinstance(health, dict):
            try:
                health = json.loads(str(health or '{}'))
            except (TypeError, ValueError, json.JSONDecodeError):
                health = {'status': 'unknown', 'detail': truncate_text(str(health or 'No health payload'), 800)}
        status = str(health.get('status', 'unknown')).strip().lower()

        def state_line(key, fallback='unknown'):
            value = health.get(key, fallback)
            if isinstance(value, bool):
                return 'Available' if value else 'Missing'
            return truncate_text(str(value or fallback), 120)
        embed = create_info_embed('AxionHost LXD Node Status', f"Node: **{truncate_text(str(node.get('name') or selected_node), 100)}**\nOverall: **{status.upper()}**")
        add_field(embed, 'LXD CLI', state_line('kvm_device'), True)
        add_field(embed, 'LXD daemon', state_line('virsh_available'), True)
        add_field(embed, 'LXD storage', state_line('qemu_img_available'), True)
        add_field(embed, 'Network Mode', state_line('network_mode', KVM_NETWORK_MODE), True)
        add_field(embed, 'Health Detail', truncate_text(str(health.get('detail') or health.get('message') or 'Host health payload received.'), 900), False)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except Exception as exc:
        await ctx.send(embed=create_error_embed('LXD Status Failed', safe_error_summary('LXD health check', exc)))
async def _get_owned_vps_for_status(ctx, reference: str):
    owner_id, _index, vps = find_vps_record(reference)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', 'Use the VPS ID or exact container name shown by your VPS list.'))
        return None
    if str(ctx.author.id) != str(owner_id) and (not is_admin_user(ctx.author)):
        await ctx.send(embed=create_error_embed('Permission Denied', 'Only the VPS owner or an AXIONHOST administrator can view this status.'))
        return None
    return (owner_id, vps)
async def ssh_status(ctx, reference: str):
    """Check persisted SSH readiness and probe the guest's SSH service without showing credentials."""
    resolved = await _get_owned_vps_for_status(ctx, reference)
    if not resolved:
        return
    _owner_id, vps = resolved
    container_name = str(vps.get('container_name') or '')
    node_id = int(vps.get('node_id') or find_node_id_for_container(container_name))
    unit_probe = 'SSH_SERVICE_UNKNOWN'
    port_probe = 'SSH_PORT_UNKNOWN'
    try:
        output = await asyncio.wait_for(_exec_guest_bash(container_name, node_id, "set +e\nif systemctl is-active --quiet ssh 2>/dev/null || systemctl is-active --quiet sshd 2>/dev/null; then echo SSH_SERVICE_ACTIVE; else echo SSH_SERVICE_INACTIVE; fi\nif (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -E '(^|[[:space:]])(0\\.0\\.0\\.0|\\[::\\]|\\*):22([[:space:]]|$)' >/dev/null; then echo SSH_PORT_LISTENING; else echo SSH_PORT_NOT_LISTENING; fi", timeout=20), timeout=23)
        output = str(output or '')
        unit_probe = 'Active' if 'SSH_SERVICE_ACTIVE' in output else 'Inactive' if 'SSH_SERVICE_INACTIVE' in output else 'Unknown'
        port_probe = 'Listening' if 'SSH_PORT_LISTENING' in output else 'Not listening' if 'SSH_PORT_NOT_LISTENING' in output else 'Unknown'
    except Exception as exc:
        logger.debug('SSH status probe deferred for %s (%s)', container_name, type(exc).__name__)
    try:
        addresses = await asyncio.wait_for(get_container_addresses(container_name, node_id), timeout=30)
    except Exception:
        addresses = {'ipv4': [], 'ipv6': []}
    embed = create_info_embed('AxionHost OpenSSH Status', f'VPS: `{truncate_text(container_name, 100)}`')
    add_field(embed, 'VPS Runtime', str((await get_container_stats(container_name, node_id)).get('status', 'unknown')).upper(), True)
    add_field(embed, 'SSH Setup Record', 'Ready' if bool(vps.get('ssh_ready')) else 'Repair queued / not verified', True)
    add_field(embed, 'SSH Service', unit_probe, True)
    add_field(embed, 'Port 22', port_probe, True)
    add_field(embed, 'IPv4', ', '.join(addresses.get('ipv4') or []) or 'Not detected', False)
    add_field(embed, 'IPv6', ', '.join(addresses.get('ipv6') or []) or 'Not detected', False)
    add_field(embed, 'Security', 'Credentials are never shown by this status command. The host key is checked by SSH clients.', False)
    await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
async def docker_status(ctx, reference: str):
    """Report actual Docker installation and daemon status for an owned VPS."""
    resolved = await _get_owned_vps_for_status(ctx, reference)
    if not resolved:
        return
    _owner_id, vps = resolved
    container_name = str(vps.get('container_name') or '')
    node_id = int(vps.get('node_id') or find_node_id_for_container(container_name))
    try:
        docker_state = await asyncio.wait_for(get_container_docker_status(container_name, node_id), timeout=30)
        runtime_state = (await get_container_stats(container_name, node_id)).get('status', 'unknown')
        embed = create_info_embed('AxionHost Docker Status', f'VPS: `{truncate_text(container_name, 100)}`')
        add_field(embed, 'VPS Runtime', str(runtime_state).upper(), True)
        add_field(embed, 'Docker', str(docker_state), True)
        add_field(embed, 'Automatic Repair', 'Enabled; background guest repair rechecks installed packages and service health.', False)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except Exception as exc:
        await ctx.send(embed=create_error_embed('Docker Status Failed', safe_error_summary('Docker status', exc)))
@bot.command(name='docker-repair')
async def docker_repair_cmd(ctx):
    target = next(iter(vps_data.get(str(ctx.author.id), [])), None)
    if not target:
        await ctx.send(embed=create_error_embed('🐳 No VPS', 'This account does not have a managed VPS.'))
        return
    if maintenance_enabled() and (not is_admin_user(ctx.author)):
        await ctx.send(embed=create_warning_embed('🟠 Under maintenance', 'User VPS actions are temporarily disabled.'))
        return
    container = str(target.get('container_name') or '')
    node_id = int(target.get('node_id', 1))
    try:
        repaired = await ensure_docker_ready(container, node_id, strict=False)
        status = await get_container_docker_status(container, node_id)
        add = create_info_embed('🐳 Docker Repair', f'`{container}`')
        add_field(add, 'Status', status, False)
        add_field(add, 'Repair', '✅ Verified and ready.' if repaired else '⚠️ Docker could not be verified on this nested guest.', False)
        await ctx.send(embed=add)
    except Exception as e:
        await ctx.send(embed=create_error_embed('🐳 Docker Repair Failed', safe_error_summary('Docker repair', e)))
@bot.command(name='maintenance')
@is_admin()
async def maintenance_command(ctx, action: str='status'):
    action = action.lower().strip()
    if action == 'status':
        if maintenance_enabled():
            await ctx.send(embed=create_error_embed('🔶 Under Maintenance', '🔶 **Under Maintenance**\n🛠️ **Service maintenance in progress**\n\nThis maintenance state applies to users only. Administrators remain fully operational.'))
        else:
            await ctx.send(embed=create_success_embed('🟢 Service Operational', "Maintenance mode is **OFF**. User dashboards have returned to the VPS's live runtime status."))
        return
    if action not in {'on', 'off'}:
        await ctx.send(embed=create_error_embed('Usage', f'Use `{PREFIX}maintenance on`, `{PREFIX}maintenance off`, or `{PREFIX}maintenance status`'))
        return
    set_setting('maintenance', action)
    if action == 'on':
        await record_audit_event('system', 'Maintenance ON', 'Maintenance enabled for normal users; administrators remain operational.', user_id=ctx.author.id)
        await ctx.send(embed=create_error_embed('🔶 Under Maintenance', 'Maintenance mode is now **ON** for users.\n\n🔶 **Under Maintenance**\n🛠️ **Service maintenance in progress**\n\nAdministrators remain fully operational.'))
        return
    await record_audit_event('system', 'Maintenance OFF', 'Maintenance disabled; normal user VPS access restored.', user_id=ctx.author.id)
    await ctx.send(embed=create_success_embed('🟢 Service Operational', 'Maintenance mode is now **OFF**. User dashboards have returned to the VPS live runtime status.'))
@bot.command(name='setexpire')
@is_admin()
async def setexpire(ctx, container_name: str, days: int):
    if days <= 0:
        await ctx.send(embed=create_error_embed('Invalid Days', 'Days must be greater than 0.'))
        return
    uid, idx, vps = find_vps_record(container_name)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'`{container_name}` was not found.'))
        return
    actual_container = str(vps['container_name'])
    old_key = (actual_container, str(vps.get('expiration_date'))) if vps.get('expiration_date') else None
    vps['expiration_date'] = (datetime.now() + timedelta(days=days)).isoformat()
    if old_key:
        EXPIRATION_WARNING_SENT.discard(old_key)
        EXPIRATION_EXPIRED_NOTICE_SENT.discard(old_key)
    save_vps_data_immediate()
    await ctx.send(embed=create_success_embed('Expiration Set', f'`{actual_container}` now expires in **{days} days**.'))
@bot.command(name='extendexpire')
@is_admin()
async def extendexpire(ctx, container_name: str, days: int):
    if days <= 0:
        await ctx.send(embed=create_error_embed('Invalid Days', 'Days must be greater than 0.'))
        return
    uid, idx, vps = find_vps_record(container_name)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'`{container_name}` was not found.'))
        return
    actual_container = str(vps['container_name'])
    current = _safe_fromiso(vps.get('expiration_date')) if vps.get('expiration_date') else datetime.now()
    if current == datetime.max:
        current = datetime.now()
    old_key = (actual_container, str(vps.get('expiration_date'))) if vps.get('expiration_date') else None
    vps['expiration_date'] = (max(current, datetime.now()) + timedelta(days=days)).isoformat()
    auto_unsuspended = False
    if suspended_due_to_expiration(vps):
        try:
            node_id = int(vps.get('node_id', 1))
            try:
                await execute_vpsctl_compat(actual_container, f'start {actual_container}', node_id=node_id)
            except Exception as start_error:
                msg = str(start_error).lower()
                if 'already running' not in msg and 'is running' not in msg:
                    raise
            vps['status'] = 'running'
            vps['suspended'] = False
            await apply_internal_permissions(actual_container, node_id)
            await recreate_port_forwards(actual_container)
            auto_unsuspended = True
        except Exception as e:
            logger.warning(f'Could not auto-unsuspend {actual_container}: {e}')
    if old_key:
        EXPIRATION_WARNING_SENT.discard(old_key)
        EXPIRATION_EXPIRED_NOTICE_SENT.discard(old_key)
    save_vps_data_immediate()
    suspension_state = 'Auto-unsuspended' if auto_unsuspended else 'Preserved'
    await ctx.send(embed=create_success_embed('Expiration Extended', f'`{actual_container}` was extended by **{days} days**.\n\nSuspension: **{suspension_state}**'))
@bot.command(name='removeexpire')
@is_admin()
async def removeexpire(ctx, container_name: str):
    uid, idx, vps = find_vps_record(container_name)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'`{container_name}` was not found.'))
        return
    actual_container = str(vps['container_name'])
    old_key = (actual_container, str(vps.get('expiration_date'))) if vps.get('expiration_date') else None
    vps['expiration_date'] = None
    if old_key:
        EXPIRATION_WARNING_SENT.discard(old_key)
        EXPIRATION_EXPIRED_NOTICE_SENT.discard(old_key)
    save_vps_data_immediate()
    await ctx.send(embed=create_success_embed('Expiration Removed', f'`{actual_container}` now has no expiration date.'))
async def _resolve_backup_path(container_name: str, requested: Optional[str]=None) -> Optional[Path]:
    safe_prefix = sanitize_username_for_container(container_name)
    if requested:
        p = (VPS_BACKUP_DIR / Path(requested).name).resolve()
        try:
            p.relative_to(VPS_BACKUP_DIR.resolve())
        except ValueError:
            return None
        return p if p.is_file() else None
    candidates = sorted(VPS_BACKUP_DIR.glob(f'{safe_prefix}_*.tar.gz'))
    return candidates[-1] if candidates else None
@bot.command(name='backup-vps')
@is_admin()
async def backup_vps(ctx, container_name: str):
    uid, idx, vps = find_vps_record(container_name)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'`{container_name}` was not found.'))
        return
    container_name = str(vps['container_name'])
    node = get_node(vps.get('node_id', 1))
    if not node or not node.get('is_local'):
        await ctx.send(embed=create_error_embed('Unsupported Node', 'VPS backups currently require a local LXD node.'))
        return
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_file = VPS_BACKUP_DIR / f'{sanitize_username_for_container(container_name)}_{stamp}.tar.gz'
    await ctx.send(embed=create_info_embed('📦 VPS Backup', f'Exporting `{container_name}` to `{backup_file.name}`...'))
    try:
        await execute_vpsctl_compat(container_name, f'export {container_name} {shlex.quote(str(backup_file))} --instance-only', timeout=1800, node_id=vps.get('node_id', 1))
        if not backup_file.exists() or backup_file.stat().st_size < 1024:
            raise RuntimeError('LXD VPS export returned without a usable backup file.')
        await ctx.send(embed=create_success_embed('Backup Complete', f'Created `{backup_file.name}` ({backup_file.stat().st_size / 1024 / 1024:.1f} MiB).'))
    except Exception as e:
        await ctx.send(embed=create_error_embed('Backup Failed', safe_error_summary('VPS backup', e)))
@bot.command(name='restore-vps')
@is_admin()
async def restore_vps(ctx, container_name: str, backup_file: str=None):
    """Safely restore a local LXD VPS using a validated temporary instance and rollback rename."""
    uid, idx, vps = find_vps_record(container_name)
    if not vps:
        await ctx.send(embed=create_error_embed('VPS Not Found', f'`{container_name}` was not found.'))
        return
    container_name = str(vps['container_name'])
    node_id = int(vps.get('node_id', 1))
    node = get_node(node_id)
    if not node or not node.get('is_local'):
        await ctx.send(embed=create_error_embed('Unsupported Node', 'VPS restore currently requires a local LXD node.'))
        return
    path = await _resolve_backup_path(container_name, backup_file)
    if not path:
        await ctx.send(embed=create_error_embed('Backup Not Found', 'No valid backup file was found in the VPS backup directory.'))
        return

    class RestoreView(discord.ui.View):

        def __init__(self, admin_id):
            super().__init__(timeout=60)
            self.admin_id = str(admin_id)
            self.confirmed = False

        @discord.ui.button(label='✅ Confirm Restore', style=discord.ButtonStyle.secondary)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            if str(interaction.user.id) != self.admin_id:
                await interaction.response.send_message(embed=create_error_embed('Access Denied', 'Only the admin who started the restore can confirm.'), ephemeral=True)
                return
            self.confirmed = True
            await interaction.response.defer()
            self.stop()

        @discord.ui.button(label='❌ Cancel', style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            if str(interaction.user.id) != self.admin_id:
                await interaction.response.send_message(embed=create_error_embed('Access Denied', 'Only the admin who started the restore can cancel.'), ephemeral=True)
                return
            await interaction.response.edit_message(embed=create_info_embed('Restore Cancelled', 'No changes were made.'), view=None)
            self.stop()
    previous_status = str(vps.get('status', 'stopped')).lower()
    previous_suspended = bool(vps.get('suspended', False))
    should_run_after_restore = previous_status == 'running' and (not previous_suspended)
    temp_name = sanitize_username_for_container(f"rgnodes-restore-{int(vps.get('vmid', vps.get('id', 0)) or 0)}-{datetime.now().strftime('%H%M%S')}")[:55]
    rollback_name = sanitize_username_for_container(f"{container_name}-rollback-{datetime.now().strftime('%H%M%S')}")[:55]
    if temp_name == container_name:
        temp_name = sanitize_username_for_container(f"rgnodes-restore-{datetime.now().strftime('%Y%m%d%H%M%S')}")[:55]
    confirm_embed = create_warning_embed('⚠️ Restore VPS', f"A validated temporary LXD VPS will be imported first. The existing `{container_name}` stays untouched until validation succeeds.\n\nBackup: `{path.name}`\nPrevious state: **{('SUSPENDED' if previous_suspended else previous_status.upper())}**")
    view = RestoreView(ctx.author.id)
    await ctx.send(embed=confirm_embed, view=view)
    await view.wait()
    if not view.confirmed:
        return
    await ctx.send(embed=create_info_embed('Restoring VPS', f'Validating `{path.name}` in temporary instance `{temp_name}`...'))
    original_exists = False
    rollback_created = False
    new_instance_ready = False
    password = vps.get('root_password') or generate_strong_password()
    try:
        try:
            await execute_vpsctl_compat('', f'info {container_name}', node_id=node_id)
            original_exists = True
        except Exception:
            original_exists = False
        for stale in (temp_name, rollback_name):
            try:
                await execute_vpsctl_compat(stale, f'delete {stale} --force', node_id=node_id)
            except Exception:
                pass
        storage_pool = await resolve_storage_pool(node_id)
        await execute_vpsctl_compat(temp_name, f'import {shlex.quote(str(path))} {temp_name} --storage {shlex.quote(storage_pool)}', timeout=1800, node_id=node_id)
        with DB_LOCK:
            conn = get_db()
            try:
                forward_rows = conn.execute('SELECT host_port FROM port_forwards WHERE vps_container = ? ORDER BY host_port', (container_name,)).fetchall()
            finally:
                conn.close()
        for row in forward_rows:
            hp = int(row[0])
            for proto in ('tcp', 'udp'):
                try:
                    await execute_vpsctl_compat(temp_name, f'config device remove {temp_name} rgnodes-pf-{proto}-{hp}', node_id=node_id)
                except Exception:
                    pass
        await apply_vps_vm_config(temp_name, node_id)
        await execute_vpsctl_compat(temp_name, f'start {temp_name}', timeout=180, node_id=node_id)
        await safe_guest_install(temp_name, node_id)
        ok, result = await configure_ssh(temp_name, node_id, password)
        if not ok:
            raise RuntimeError(f'SSH validation failed: {result}')
        await set_guest_hostname(temp_name, node_id, VPS_HOSTNAME)
        await execute_vpsctl_compat(temp_name, f"exec {temp_name} -- bash -lc 'true'", timeout=60, node_id=node_id)
        await execute_vpsctl_compat(temp_name, f'stop {temp_name} --force', timeout=120, node_id=node_id)
        new_instance_ready = True
        if original_exists:
            try:
                await execute_vpsctl_compat(container_name, f'stop {container_name} --force', timeout=120, node_id=node_id)
            except Exception:
                pass
            await execute_vpsctl_compat(container_name, f'rename {container_name} {rollback_name}', timeout=180, node_id=node_id)
            rollback_created = True
        try:
            await execute_vpsctl_compat(temp_name, f'rename {temp_name} {container_name}', timeout=180, node_id=node_id)
        except Exception:
            if rollback_created:
                try:
                    await execute_vpsctl_compat(rollback_name, f'rename {rollback_name} {container_name}', timeout=180, node_id=node_id)
                except Exception:
                    pass
            raise
        if should_run_after_restore:
            await execute_vpsctl_compat(container_name, f'start {container_name}', timeout=180, node_id=node_id)
            await apply_internal_permissions(container_name, node_id)
            readded = await recreate_port_forwards(container_name)
        else:
            readded = 0
            if not previous_suspended:
                readded = 0
        await set_guest_hostname(container_name, node_id, VPS_HOSTNAME)
        vps['status'] = 'running' if should_run_after_restore else 'stopped'
        vps['suspended'] = previous_suspended
        vps['root_password'] = password
        save_vps_data_immediate()
        if rollback_created:
            try:
                await execute_vpsctl_compat(rollback_name, f'delete {rollback_name} --force', timeout=300, node_id=node_id)
            except Exception as cleanup_error:
                logger.warning(f'Restored VPS but could not delete rollback instance {rollback_name}: {cleanup_error}')
        if previous_suspended:
            await ctx.send(embed=create_success_embed('Restore Complete', f'`{container_name}` restored successfully and remains **SUSPENDED** to preserve its previous state.'))
        else:
            await ctx.send(embed=create_success_embed('Restore Complete', f"`{container_name}` restored successfully from `{path.name}`. State preserved: **{('RUNNING' if should_run_after_restore else 'STOPPED')}**. Port forwards restored: **{readded}**."))
    except Exception as e:
        logger.error(f'Restore failed for {container_name}: {e}', exc_info=True)
        try:
            if rollback_created:
                try:
                    await execute_vpsctl_compat(container_name, f'stop {container_name} --force', timeout=120, node_id=node_id)
                except Exception:
                    pass
                try:
                    await execute_vpsctl_compat(container_name, f'delete {container_name} --force', timeout=180, node_id=node_id)
                except Exception:
                    pass
                await execute_vpsctl_compat(rollback_name, f'rename {rollback_name} {container_name}', timeout=180, node_id=node_id)
                if should_run_after_restore:
                    await execute_vpsctl_compat(container_name, f'start {container_name}', timeout=180, node_id=node_id)
                    await recreate_port_forwards(container_name)
        except Exception as rollback_error:
            logger.critical(f'ROLLBACK FAILED for {container_name}: {rollback_error}', exc_info=True)
        try:
            await execute_vpsctl_compat(temp_name, f'delete {temp_name} --force', timeout=180, node_id=node_id)
        except Exception:
            pass
        vps['status'] = previous_status if previous_status in {'running', 'stopped'} else 'stopped'
        vps['suspended'] = previous_suspended
        save_vps_data_immediate()
        await ctx.send(embed=create_error_embed('Restore Failed', 'The restore was not committed safely. Original VPS state was preserved where possible. ' + safe_error_summary('VPS restore', e)))
async def process_vps_renewal(vps: Dict[str, Any], requested_days: int=None, user_initiated: bool=False) -> tuple[bool, str]:
    """Central renewal logic: owner can renew in the last two days or after expiry; admins can renew anytime."""
    days = int(requested_days or VPS_RENEWAL_DAYS)
    if days <= 0:
        return (False, 'Renewal duration must be greater than zero.')
    now = datetime.now()
    raw = vps.get('expiration_date')
    try:
        current = datetime.fromisoformat(str(raw)) if raw else now
    except (TypeError, ValueError):
        current = now
    seconds_left = (current - now).total_seconds()
    window = max(0, RENEWAL_WINDOW_DAYS) * 86400
    if user_initiated and seconds_left > window:
        left = max(1, int(seconds_left // 86400))
        return (False, f'Renewal opens during the final **{RENEWAL_WINDOW_DAYS} days** before expiry. Your VPS still has about **{left} days** remaining.')
    container = str(vps['container_name'])
    old_key = (container, str(raw)) if raw else None
    was_expiry_suspended = suspended_due_to_expiration(vps)
    new_expiration = max(current, now) + timedelta(days=days)
    if was_expiry_suspended:
        node_id = int(vps.get('node_id', 1))
        try:
            try:
                await execute_vpsctl_compat(container, f'start {container}', timeout=180, node_id=node_id)
            except Exception as e:
                msg = str(e).lower()
                if 'already running' not in msg and 'is running' not in msg:
                    raise
            vps['status'] = 'running'
            vps['suspended'] = False
            await apply_internal_permissions(container, node_id)
            await install_anti_mining_guard(container, node_id)
            await recreate_port_forwards(container)
        except Exception as e:
            return (False, 'The VPS could not be safely restarted, so renewal was not committed. ' + safe_error_summary('VPS restart during renewal', e))
    vps['expiration_date'] = new_expiration.isoformat()
    if old_key:
        EXPIRATION_WARNING_SENT.discard(old_key)
        EXPIRATION_EXPIRED_NOTICE_SENT.discard(old_key)
    save_vps_data_immediate()
    state = '✅ Auto-unsuspended' if was_expiry_suspended and (not vps.get('suspended')) else '✅ State preserved'
    return (True, f"`{container}` renewed for **{days} days**.\n**New expiry:** `{new_expiration.strftime('%Y-%m-%d %H:%M:%S')}`\n**Suspension:** {state}")
@bot.command(name='renew')
async def renew_user(ctx, container_name: str=None):
    """User renewal command. Adds 60 days during the final two-day window."""
    owner_id = str(ctx.author.id)
    owned = list(vps_data.get(owner_id, []))
    if not owned:
        await ctx.send(embed=create_error_embed('No VPS Found', 'You do not currently own a VPS.'))
        return
    if container_name:
        wanted = str(container_name).strip()
        target = next((v for v in owned if str(v.get('container_name')) == wanted or str(v.get('id')) == wanted or str(v.get('vmid')) == wanted), None)
    elif len(owned) == 1:
        target = owned[0]
    else:
        await ctx.send(embed=create_warning_embed('Select a VPS', f'Usage: `{PREFIX}renew <vps-id-or-name>`'))
        return
    if not target:
        await ctx.send(embed=create_error_embed('VPS Not Found', 'That VPS does not belong to your account.'))
        return
    ok, message = await process_vps_renewal(target, VPS_RENEWAL_DAYS, user_initiated=True)
    if not ok:
        await ctx.send(embed=create_warning_embed('Renewal Unavailable', message))
        return
    await ctx.send(embed=create_success_embed('⏰ VPS Renewed', message))
    try:
        await ctx.author.send(embed=create_success_embed('⏰ VPS Renewed', message))
    except Exception:
        pass
@bot.command(name='announce', aliases=['announcement', 'notify-vps'])
@is_admin()
async def announce_command(ctx, announcement_type: str=None, *, custom_message: str=''):
    """Send a service announcement by DM to current VPS owners only."""
    kind = str(announcement_type or '').strip().lower()
    custom_message = str(custom_message or '').strip()
    presets = {
        'online': ('🟢 AxionHost Online', 'AxionHost VPS service is **ONLINE** again. Your VPS services are available normally.'),
        'offline': ('🔴 AxionHost Offline', 'AxionHost VPS service will be **OFFLINE** temporarily for maintenance. Please save your work.'),
        '30min': ('🟠 Maintenance in 30 Minutes', 'AxionHost will enter **maintenance in approximately 30 minutes**. Please save your work and keep your VPS prepared for a short service interruption.'),
        '30m': ('🟠 Maintenance in 30 Minutes', 'AxionHost will enter **maintenance in approximately 30 minutes**. Please save your work and keep your VPS prepared for a short service interruption.'),
        '30': ('🟠 Maintenance in 30 Minutes', 'AxionHost will enter **maintenance in approximately 30 minutes**. Please save your work and keep your VPS prepared for a short service interruption.'),
    }
    if kind == 'custom':
        if not custom_message:
            await ctx.send(embed=create_error_embed('📢 Message Required', f'Usage: `{PREFIX}announce custom <message>`'))
            return
        title, message = '📢 AxionHost Announcement', custom_message
    elif kind in presets:
        title, message = presets[kind]
        if custom_message:
            message = custom_message
    elif kind:
        title, message = '📢 AxionHost Announcement', ' '.join((announcement_type, custom_message)).strip()
    else:
        await ctx.send(embed=create_error_embed('📢 Announcement Usage', f'`{PREFIX}announce online`\n`{PREFIX}announce offline`\n`{PREFIX}announce 30min`\n`{PREFIX}announce custom <message>`'))
        return
    if not message or len(message) > 1800:
        await ctx.send(embed=create_error_embed('📏 Invalid Message', 'Announcement must contain 1–1800 characters.'))
        return
    recipients=[]
    seen=set()
    for owner_id, items in vps_data.items():
        if not items:
            continue
        try:
            uid=int(owner_id)
        except (TypeError, ValueError):
            continue
        if uid not in seen:
            seen.add(uid)
            recipients.append(uid)
    if not recipients:
        await ctx.send(embed=create_warning_embed('📢 No VPS Owners', 'No users currently have a managed VPS, so no DMs were sent.'))
        return
    embed=create_info_embed(title, message)
    add_field(embed, '👥 Recipients', 'Only current managed VPS owners', False)
    embed.set_footer(text=f'{BOT_NAME} • VPS Service Notification')
    confirm=create_warning_embed('📢 Confirm VPS Announcement', f'This will DM **{len(recipients)}** current VPS owner(s) only.\n\n**Type:** `{kind or "custom"}`\n**Message:**\n{message}\n\nUsers without a managed VPS will **not** receive it.')
    class AnnouncementConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.finished=False
        @discord.ui.button(label='✅ Send to VPS Owners', style=discord.ButtonStyle.secondary)
        async def send_now(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(embed=create_error_embed('⛔ Access Denied', 'Only the admin who created this announcement can confirm it.'), ephemeral=True)
                return
            if self.finished:
                return
            self.finished=True
            await interaction.response.defer()
            self.stop()
            sent=failed=0
            for uid in recipients:
                try:
                    user=await bot.fetch_user(uid)
                    await user.send(embed=embed)
                    sent += 1
                except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
                    failed += 1
                    logger.warning('Announcement DM failed for user %s: %s', uid, type(exc).__name__)
                except Exception as exc:
                    failed += 1
                    logger.warning('Announcement DM unexpected failure for user %s: %s', uid, type(exc).__name__)
                await asyncio.sleep(1.0)
            await record_audit_event('system', 'VPS Owner Announcement Sent', f'Announcement type={kind or "custom"}; eligible={len(recipients)}; sent={sent}; failed={failed}.', user_id=ctx.author.id, announce=False)
            await interaction.followup.send(embed=create_success_embed('📨 Announcement Complete', f'✅ Delivered: **{sent}**\n⚠️ Failed/DM blocked: **{failed}**\n👥 Eligible VPS owners: **{len(recipients)}**'))
        @discord.ui.button(label='❌ Cancel', style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(embed=create_error_embed('⛔ Access Denied', 'Only the admin who created this announcement can cancel it.'), ephemeral=True)
                return
            if self.finished:
                return
            self.finished=True
            await interaction.response.edit_message(embed=create_info_embed('📢 Announcement Cancelled', 'No VPS-owner DMs were sent.'), view=None)
            self.stop()
    await ctx.send(embed=confirm, view=AnnouncementConfirmView())

@bot.command(name='dm-mass')
@is_admin()
async def dm_mass(ctx, *, message: str=None):
    """Send an admin announcement only to users who currently own managed VPS records."""
    message = (message or '').strip()
    if not message:
        await ctx.send(embed=create_error_embed('📢 Message Required', f'Usage: `{PREFIX}dm-mass <message>`'))
        return
    if len(message) > 1800:
        await ctx.send(embed=create_error_embed('📏 Message Too Long', 'Keep the announcement below 1800 characters.'))
        return
    recipients = []
    seen = set()
    for owner_id, items in vps_data.items():
        if not items:
            continue
        try:
            uid = int(owner_id)
        except (TypeError, ValueError):
            continue
        if uid not in seen:
            seen.add(uid)
            recipients.append(uid)
    if not recipients:
        await ctx.send(embed=create_warning_embed('📢 No VPS Users', 'No users currently own a managed VPS.'))
        return
    confirm = create_warning_embed('📢 VPS User Announcement', f'This will DM **{len(recipients)}** current VPS owner(s).\n\n**Message:**\n{message}\n\nContinue?')

    class DMConfirmView(discord.ui.View):

        def __init__(self):
            super().__init__(timeout=60)
            self.confirmed = False

        @discord.ui.button(label='✅ Send', style=discord.ButtonStyle.secondary)
        async def send_now(self, interaction: discord.Interaction, button: discord.ui.Button):
            if str(interaction.user.id) != str(ctx.author.id):
                await interaction.response.send_message(embed=create_error_embed('⛔ Access Denied', 'Only the admin who started this announcement can confirm it.'), ephemeral=True)
                return
            self.confirmed = True
            await interaction.response.defer()
            self.stop()
            sent = failed = 0
            announcement = create_info_embed('📢 AxionHost Announcement', message)
            add_field(announcement, 'ℹ️ Scope', 'Sent only to users with a managed VPS record.', False)
            for uid in recipients:
                try:
                    user = await bot.fetch_user(uid)
                    await user.send(embed=announcement)
                    sent += 1
                except (discord.Forbidden, discord.NotFound, discord.HTTPException) as e:
                    failed += 1
                    logger.warning(f'DM mass delivery failed for {uid}: {e}')
                await asyncio.sleep(1.0)
            await interaction.followup.send(embed=create_success_embed('📨 Announcement Complete', f'✅ Sent: **{sent}**\n⚠️ Failed/blocked: **{failed}**\n👥 Eligible: **{len(recipients)}**'))

        @discord.ui.button(label='❌ Cancel', style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            if str(interaction.user.id) != str(ctx.author.id):
                await interaction.response.send_message(embed=create_error_embed('⛔ Access Denied', 'Only the admin who started this announcement can cancel it.'), ephemeral=True)
                return
            await interaction.response.edit_message(embed=create_info_embed('📢 Announcement Cancelled', 'No DMs were sent.'), view=None)
            self.stop()
    await ctx.send(embed=confirm, view=DMConfirmView())
@bot.command(name='ssh')
async def ssh_command(ctx, container_name: str=None):
    """Send normal OpenSSH access details privately."""
    caller_id = str(ctx.author.id)
    if maintenance_enabled() and (not is_admin_user(ctx.author)):
        await ctx.send(embed=create_warning_embed('🟠 Under maintenance', 'User VPS actions are temporarily disabled.'))
        return
    admin = is_admin_user(ctx.author)
    owned = list(vps_data.get(caller_id, []))
    target_user_id = caller_id
    target = None
    if container_name:
        target_user_id, _, target = find_vps_record(container_name)
        if not target:
            await ctx.send(embed=create_error_embed('🖥️ VPS Not Found', f'No VPS was found for `{container_name}`.'))
            return
        if not admin and str(target_user_id) != caller_id:
            await ctx.send(embed=create_error_embed('⛔ Access Denied', 'You can only open SSH for your own VPS.'))
            return
    elif len(owned) == 1:
        target = owned[0]
    else:
        await ctx.send(embed=create_warning_embed('🖥️ Select a VPS', f'Usage: `{PREFIX}ssh <vmid|vps-name>`'))
        return
    container = str(target.get('container_name') or '')
    node_id = int(target.get('node_id', 1))
    if target.get('suspended'):
        await ctx.send(embed=create_error_embed('⛔ VPS Suspended', 'Renew or ask support to unsuspend this VPS.'))
        return
    try:
        stats = await asyncio.wait_for(get_container_stats(container, node_id), timeout=20)
        if str(stats.get('status', '')).lower() != 'running':
            await ctx.send(embed=create_warning_embed('⏸️ VPS Not Running', f'`{container}` is stopped. Start it first.'))
            return
        endpoints = await detect_public_endpoints(node_id, container)
        ssh_port = 22 if KVM_NETWORK_MODE in {'direct', 'bridge'} else None
        if not ssh_port:
            forwards = get_user_forwards(target_user_id)
            ssh_port = next((int(f['host_port']) for f in forwards if str(f.get('vps_container')) == container and int(f.get('vps_port', 0)) == 22), None)
            if not ssh_port:
                ssh_port = await create_port_forward(target_user_id, container, 22, node_id)
        access_info = format_public_ssh_access(endpoints, ssh_port)
        access = create_success_embed('💻 AxionHost SSH', f'`{container}` • `{VPS_HOSTNAME}`')
        if access_info.get('ssh_ipv4'):
            add_field(access, '💻 SSH IPv4', f"```bash\n{access_info['ssh_ipv4']}\n```", False)
        else:
            add_field(access, '💻 SSH IPv4', '⚠️ Public IPv4 unavailable on this node.', False)
        if access_info.get('ssh_ipv6'):
            add_field(access, '🌐 SSH IPv6', f"```bash\n{access_info['ssh_ipv6']}\n```", False)
        else:
            add_field(access, '🌐 SSH IPv6', '⚪ Public IPv6 unavailable on this node.', False)
        add_field(access, '🔐 Credentials', f"Username: `root`\nPassword: `{target.get('root_password') or 'not available'}`", False)
        add_field(access, '🔗 Separation', 'This sends normal OpenSSH access details only.', False)
        try:
            recipient = await bot.fetch_user(int(target_user_id))
            await recipient.send(embed=access)
            await ctx.send(embed=create_success_embed('📨 SSH Sent', 'SSH-only access details were sent to your DM.'))
        except discord.Forbidden:
            logger.info('SSH credentials DM was blocked for owner ID %s; no credentials were posted publicly.', target_user_id)
            await ctx.send(embed=create_warning_embed('🔒 Private SSH Details Not Delivered', "Discord blocked the VPS owner's DM. Enable DMs from this server and retry. For safety, the root password and SSH details were **not** posted in this channel."))
    except Exception as e:
        logger.error('SSH command failed for %s (%s)', container, type(e).__name__)
        await ctx.send(embed=create_error_embed('💻 SSH Failed', 'SSH details could not be generated or delivered. Check that the VPS is running and has a reachable public endpoint; private credentials were not posted here.'))
@bot.command(name='pinggy')
async def pinggy_command(ctx, container_name: str=None):
    """Open Pinggy SSH tunnel only."""
    caller_id = str(ctx.author.id)
    if maintenance_enabled() and (not is_admin_user(ctx.author)):
        await ctx.send(embed=create_warning_embed('🟠 Under maintenance', 'User VPS actions are temporarily disabled.'))
        return
    admin = is_admin_user(ctx.author)
    target_user_id = caller_id
    target = None
    if container_name:
        target_user_id, _, target = find_vps_record(container_name)
        if not target:
            await ctx.send(embed=create_error_embed('🖥️ VPS Not Found', f'No VPS was found for `{container_name}`.'))
            return
        if not admin and str(target_user_id) != caller_id:
            await ctx.send(embed=create_error_embed('⛔ Access Denied', 'You can only open Pinggy for your own VPS.'))
            return
    else:
        owned = list(vps_data.get(caller_id, []))
        if len(owned) != 1:
            await ctx.send(embed=create_warning_embed('🖥️ Select a VPS', f'Usage: `{PREFIX}pinggy <vmid|container-name>`'))
            return
        target = owned[0]
    container = str(target.get('container_name') or '')
    node_id = int(target.get('node_id', 1))
    if target.get('suspended'):
        await ctx.send(embed=create_error_embed('⛔ VPS Suspended', 'Renew or ask support to unsuspend this VPS.'))
        return
    try:
        stats = await asyncio.wait_for(get_container_stats(container, node_id), timeout=20)
        if str(stats.get('status', '')).lower() != 'running':
            await ctx.send(embed=create_warning_embed('⏸️ VPS Not Running', f'`{container}` is stopped. Start it first.'))
            return
        info = await asyncio.wait_for(start_pinggy_session(container, node_id), timeout=100)
        if not info:
            raise RuntimeError('Pinggy returned no public endpoint. Try again or use Reconnect Pinggy.')
        e = create_success_embed('🌐 AxionHost Pinggy Connected', f'`{container}` • `{VPS_HOSTNAME}`')
        add_field(e, '🌐 Pinggy SSH Tunnel', f"**SSH Command:** `ssh root@{info['host']} -p {info['port']}`\n**Host:** `{info['host']}`\n**Port:** `{info['port']}`\n**Status:** 🟢 Tunnel Active", False)
        add_field(e, '🔗 Separation', 'Pinggy only. Normal SSH access is managed separately.', False)
        try:
            recipient = await bot.fetch_user(int(target_user_id))
            await recipient.send(embed=e)
            await ctx.send(embed=create_success_embed('📨 Pinggy Sent', 'Pinggy-only access details were sent to your DM.'))
        except discord.Forbidden:
            logger.info('Pinggy endpoint DM was blocked for owner ID %s; endpoint was not posted publicly.', target_user_id)
            await ctx.send(embed=create_warning_embed('🔒 Private Pinggy Details Not Delivered', "Discord blocked the VPS owner's DM. Enable DMs from this server and retry. For safety, the private tunnel endpoint was **not** posted in this channel."))
    except Exception as e:
        logger.error('Pinggy command failed for %s (%s)', container, type(e).__name__)
        await ctx.send(embed=create_error_embed('🌐 Pinggy Failed', 'Pinggy could not create or deliver a tunnel. Check VPS status and try reconnecting. Private tunnel endpoints and diagnostic payloads are hidden.'))
@bot.command(name='reconnect-pinggy')
async def reconnect_pinggy_command(ctx, container_name: str=None):
    """Reconnect Pinggy only; normal SSH access is managed separately."""
    await pinggy_command.callback(ctx, container_name)
async def send_private_node_setup(recipient, node_id, node_name, node_url, api_key, rotate=False):
    """Deliver remote-node credentials over DM only; never put API secrets in a channel embed."""
    embed = create_info_embed('Private Remote Node Key Rotation' if rotate else 'Private Remote Node Setup', f'Node **{node_name}** (ID: {node_id})\nKeep this message private. Anyone with the API key may control this node through the bot.')
    add_field(embed, 'Node URL', str(node_url), False)
    add_field(embed, 'API Key', f'`{api_key}`', False)
    command = 'sudo bash node.sh --prompt-api-key --port=18443'
    add_field(embed, 'Install / Update', f'Upload the complete AxionHost release bundle (including `node.sh`, `lxd_vpsctl.py`, and `lxd_node_agent.py`) to the Linux node, then run:\n```bash\n{command}\n```\nThe command deliberately forces a hidden key prompt, even if an older key already exists in the node config. Paste the API key from this DM; input is not echoed. Do not put the key directly in a shell command or share this DM.', False)
    add_field(embed, 'Network Setup', 'The agent binds to `127.0.0.1` by default and does not open firewall ports. For remote access, use a private VPN and bind with `--host=NODE_VPN_IP`, or put the loopback listener behind a TLS reverse proxy/Cloudflare Tunnel and register its HTTPS URL. Do not expose plain HTTP to the public Internet.', False)
    try:
        await recipient.send(embed=embed)
        return True
    except Exception as exc:
        logger.warning('Could not send private node setup details to Discord user ID %s (%s). No API key was posted publicly.', getattr(recipient, 'id', 'unknown'), type(exc).__name__)
        return False
def _make_discord_user_agent(bot_name: str, bot_version: str) -> str:
    """Build a strictly ASCII HTTP User-Agent; brand names may include Unicode ™."""
    safe_name = re.sub('[^A-Za-z0-9._-]', '', str(bot_name).encode('ascii', 'ignore').decode('ascii'))
    safe_version = re.sub('[^A-Za-z0-9._-]', '', str(bot_version).encode('ascii', 'ignore').decode('ascii'))
    safe_name = safe_name or 'AXIONHOSTBot'
    safe_version = safe_version or '1.0'
    return f'{safe_name}/{safe_version} (Discord bot)'
def discord_token_preflight(token: str) -> bool:
    """Validate the configured bot token with Discord REST without logging the secret."""
    try:
        response = requests.get('https://discord.com/api/v10/users/@me', headers={'Authorization': f'Bot {token}', 'User-Agent': _make_discord_user_agent(BOT_NAME, BOT_VERSION)}, timeout=8)
        if response.status_code == 200:
            logger.info('✅ Discord token preflight passed.')
            return True
        if response.status_code == 401:
            logger.error('❌ Discord rejected the configured token (HTTP 401). Reset/copy the Bot Token from Developer Portal → Bot.')
            return False
        if response.status_code == 429:
            logger.warning('⚠️ Discord token preflight was rate-limited; gateway login will be attempted normally.')
            return True
        logger.warning('⚠️ Discord token preflight returned HTTP %s; gateway login will be attempted normally.', response.status_code)
        return True
    except (requests.RequestException, UnicodeError, ValueError) as exc:
        logger.warning('⚠️ Discord token preflight could not complete safely (%s); gateway login will be attempted normally.', type(exc).__name__)
        return True
    except Exception as exc:
        logger.warning('⚠️ Discord token preflight encountered an unexpected %s; gateway login will be attempted normally.', type(exc).__name__)
        return True
def run_self_check() -> int:
    """Non-destructive diagnostics for the configured role: remote controller or local LXD node."""
    problems = []
    role = 'remote-only Discord controller' if REMOTE_NODE_ONLY else 'local LXD host'
    logger.info('🧪 AxionHost VPS-only deep self-check')
    logger.info('Role: %s • Provider: %s • Processor: %s', role, HOST_PROVIDER_NAME, HOST_PROCESSOR_NAME)
    if REMOTE_NODE_ONLY:
        try:
            node_id = _preferred_deployment_node_id()
            node = get_node(node_id)
            if not node or bool(node.get('is_local')):
                raise RuntimeError('preferred deployment node is missing or marked local')
            node_url = str(node.get('url') or '').rstrip('/')
            api_key = str(node.get('api_key') or '')
            if not node_url or not api_key:
                raise RuntimeError('remote node URL or API key is missing')
            headers = {'X-API-Key': api_key, 'User-Agent': _make_discord_user_agent(BOT_NAME, BOT_VERSION)}
            ping = requests.get(f'{node_url}/api/ping', headers=headers, timeout=6)
            if ping.status_code != 200:
                raise RuntimeError(f'remote node ping returned HTTP {ping.status_code}')
            ping_payload = ping.json()
            if not isinstance(ping_payload, dict) or ping_payload.get('status') != 'ok':
                raise RuntimeError('remote node ping returned an unexpected payload')
            logger.info('✅ Remote node %s (ID %s) agent authentication and ping passed.', node.get('name', 'NODE - 1'), node_id)
            controller_path = str(node.get('vpsctl_path') or '/usr/local/sbin/vpsctl')
            health_command = f'{shlex.quote(controller_path)} compat health'
            health_response = requests.post(f'{node_url}/api/execute', json={'command': health_command}, headers=headers, timeout=15)
            if health_response.status_code != 200:
                raise RuntimeError(f'remote LXD health probe returned HTTP {health_response.status_code}')
            health_payload = health_response.json()
            if not isinstance(health_payload, dict):
                raise RuntimeError('remote LXD health probe returned invalid JSON')
            if int(health_payload.get('returncode', 0) or 0) != 0:
                detail = _safe_diagnostic_text(health_payload.get('stderr') or health_payload.get('error') or 'LXD health probe failed')
                raise RuntimeError(f'remote LXD readiness failed: {detail}')
            try:
                health = json.loads(str(health_payload.get('stdout') or '{}'))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError('remote LXD health probe stdout was not valid JSON') from exc
            if not isinstance(health, dict) or health.get('status') != 'ok' or health.get('backend') != 'LXD/LXC':
                raise RuntimeError('remote LXD health probe did not report a ready LXD/LXC backend')
            logger.info('✅ Remote LXD/LXC readiness passed; network mode=%s; LXD=%s.', health.get('network_mode', 'unknown'), bool(health.get('lxd_available')))
            if not health.get('public_ipv4_pool_configured'):
                logger.info('LXD bridge networking selected; guest access uses node-side port forwarding or a provider-routed public network.')
        except Exception as exc:
            detail = _safe_diagnostic_text(exc)
            problems.append('remote node/LXD check failed: ' + detail)
            logger.error('❌ Remote-only self-check failed: %s', detail)
    else:
        controller = _find_kvm_vpsctl()
        if controller:
            logger.info('✅ Hash-verified LXD VPS controller: %s', controller)
        else:
            problems.append('LXD controller is missing or failed integrity verification')
            logger.error('❌ Trusted embedded LXD controller could not be installed/found; run setup.sh as root and verify /usr/local/sbin is writable.')
        if shutil.which('lxc') and _dashboard_probe_command([shutil.which('lxc'), 'info'], 3.0)[0]:
            logger.info('✅ LXD daemon is available.')
        else:
            problems.append('LXD daemon is unavailable')
            logger.error('❌ LXD daemon is unavailable. Install and initialize LXD.')
        for binary in ('lxc',):
            if shutil.which(binary):
                logger.info('✅ %s available at %s', binary, shutil.which(binary))
            else:
                problems.append(f'{binary} is missing')
                logger.error('❌ %s is missing; run setup.sh.', binary)
        if KVM_NETWORK_MODE not in {'direct', 'bridge', 'lxd-managed'}:
            problems.append('LXD network mode must be lxd-managed (or direct/bridge when provider supports routed guest IPs)')
            logger.error('❌ Invalid LXD network mode=%s', KVM_NETWORK_MODE)
        elif KVM_NETWORK_MODE == 'direct' and (not PUBLIC_PARENT_INTERFACE):
            problems.append('PUBLIC_PARENT_INTERFACE is not configured')
            logger.error('❌ PUBLIC_PARENT_INTERFACE is empty; node.sh should auto-detect the uplink.')
        elif KVM_NETWORK_MODE == 'bridge' and (not PUBLIC_BRIDGE_NAME):
            problems.append('PUBLIC_BRIDGE_NAME is not configured')
            logger.error('❌ PUBLIC_BRIDGE_NAME is empty for bridge mode.')
        if REAL_PUBLIC_IPV4_REQUIRED and KVM_NETWORK_MODE != 'lxd-managed' and (not (PUBLIC_PARENT_INTERFACE or PUBLIC_BRIDGE_NAME or PUBLIC_IPV4_POOL_CIDR)):
            problems.append('no real public IPv4 network source is configured')
            logger.error('❌ No real public IPv4 network source is configured.')
    if DISCORD_TOKEN:
        fingerprint = hashlib.sha256(DISCORD_TOKEN.encode()).hexdigest()[:12]
        logger.info('✅ Discord token is configured (length=%d, sha256[:12]=%s).', len(DISCORD_TOKEN), fingerprint)
    else:
        problems.append('DISCORD_TOKEN is empty')
        logger.error('❌ DISCORD_TOKEN is empty.')
    logger.info('Resource policy: initial=%s GiB RAM/%s CPU/%s GiB disk • max=%s GiB RAM/%s CPU/%s GiB disk • autoscale=%s • disk-scale=%s%%/%sGiB', INITIAL_VPS_RAM_GB, INITIAL_VPS_CPU, INITIAL_VPS_DISK_GB, VPS_MAX_RAM_GB, VPS_MAX_CPU, VPS_MAX_DISK_GB, RESOURCE_AUTOSCALE_ENABLED, RESOURCE_SCALE_UP_DISK_THRESHOLD, RESOURCE_SCALE_UP_DISK_STEP_GB)
    logger.info('Protection: anti-mining=%s • guest hardening=cloud-init+fail2ban+sysctl • embeds=colorless', ANTI_MINING_ENABLED)
    if problems:
        logger.error('❌ Self-check found %d issue(s): %s', len(problems), '; '.join(problems))
        return 2
    logger.info('✅ Self-check passed for the configured deployment role.')
    return 0
# Run the bot
if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == 'your_discord_bot_token_here':
        logger.error("❌ ERROR: No valid Discord token found!")
        logger.error("Please update your .env file with a valid Discord bot token.")
        logger.error("DISCORD_TOKEN is missing or still set to the placeholder; token value was not logged for security.")
        exit(1)
    try:
        bot.run(DISCORD_TOKEN)
    except discord.errors.LoginFailure as e:
        logger.error(f"❌ ERROR: Failed to login with Discord token: {e}")
        logger.error("Please check your DISCORD_TOKEN in the .env file.")
        exit(1)

