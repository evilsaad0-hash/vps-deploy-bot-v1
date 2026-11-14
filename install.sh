#!/bin/bash
# ============================================================
#  Evil Vps V1 — Installer
#  Sets up LXD/LXC, Python deps, systemd service for bot.py
# ============================================================

set -e

# ---------- Colors ----------
RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'; BLU='\033[0;34m'
MAG='\033[0;35m'; CYN='\033[0;36m'; WHT='\033[1;37m'; NC='\033[0m'

rainbow_line() {
    local text="$1"
    local colors=("$RED" "$YEL" "$GRN" "$CYN" "$BLU" "$MAG")
    local i=0
    for (( j=0; j<${#text}; j++ )); do
        c=${colors[$((i % 6))]}
        printf '%b%s%b' "$c" "${text:$j:1}" "$NC"
        i=$((i+1))
    done
    echo ""
}

ascii_banner() {
    echo -e "${MAG}"
    cat <<'ART'

 ███████╗██╗   ██╗██╗██╗      ███████╗ █████╗  █████╗ ██████╗
 ██╔════╝██║   ██║██║██║      ██╔════╝██╔══██╗██╔══██╗██╔══██╗
 █████╗  ██║   ██║██║██║      ███████╗███████║███████║██║  ██║
 ██╔══╝  ╚██╗ ██╔╝██║██║      ╚════██║██╔══██║██╔══██║██║  ██║
 ███████╗ ╚████╔╝ ██║███████╗ ███████║██║  ██║██║  ██║██████╔╝
 ╚══════╝  ╚═══╝  ╚═╝╚══════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝

                     ██╗   ██╗██████╗ ███████╗    
                     ██║   ██║██╔══██╗██╔════╝    
                     ██║   ██║██████╔╝███████╗   
                     ╚██╗ ██╔╝██╔═══╝ ╚════██║    
                      ╚████╔╝ ██║     ███████║    
                        ╚═══╝  ╚═╝     ╚══════╝    
ART
    echo -e "${CYN}                 >>> VPS DISCORD BOT INSTALLER <<<${NC}"
    echo -e "${YEL}                         MADE BY EVILSAAD${NC}\n"
}

banner() {
    clear
    ascii_banner
    echo -e "${WHT}  ─────────────────────────────────────────────────────────────${NC}"
    echo -e "  ${CYN}Fully Automated LXC/LXD VPS Discord Bot Installer${NC}"
    echo -e "  ${CYN}Ubuntu & Debian supported | Fast setup${NC}"
    echo -e "  ${MAG}Made by EvilSaad${NC}  |  ${BLU}github.com/evilsaad0-hash/evm-v3${NC}"
    echo -e "${WHT}  ─────────────────────────────────────────────────────────────${NC}\n"
}

step()  { echo -e "${GRN}[+]${NC} $1"; }
warn()  { echo -e "${YEL}[!]${NC} $1"; }
err()   { echo -e "${RED}[x]${NC} $1"; }

need_root() {
    if [ "$EUID" -ne 0 ]; then
        err "Please run this script as root (sudo ./install.sh)"
        exit 1
    fi
}

# ---------- OS selection ----------
choose_os() {
    echo -e "${WHT}Select your OS:${NC}"
    echo -e "  ${YEL}1)${NC} Ubuntu"
    echo -e "  ${YEL}2)${NC} Debian"
    read -rp "$(echo -e "${CYN}Enter choice [1-2]: ${NC}")" OS_CHOICE
}

install_lxd_ubuntu() {
    step "Updating system (Ubuntu)..."
    apt update && apt upgrade -y

    step "Installing LXC utilities..."
    apt install lxc lxc-utils -y

    step "Installing snapd..."
    apt install snapd -y
    systemctl enable --now snapd.socket

    step "Installing LXD via snap..."
    if ! snap list lxd >/dev/null 2>&1; then
        snap install lxd
    else
        step "LXD snap is already installed."
    fi
    snap wait system seed.loaded || true

    step "Adding $SUDO_USER to lxd group..."
    usermod -aG lxd "${SUDO_USER:-$USER}" || true

    step "Initializing LXD (auto/minimal config)..."
    lxd init --auto

    step "Installing bridge/uidmap utilities..."
    apt update
    apt install lxc lxc-utils bridge-utils uidmap -y
}

install_lxd_debian() {
    step "Updating system (Debian)..."
    apt update && apt upgrade -y

    step "Installing snapd..."
    apt install snapd -y
    systemctl enable --now snapd.socket

    step "Linking snap directory..."
    ln -sf /var/lib/snapd/snap /snap

    step "Installing LXD via snap..."
    if ! snap list lxd >/dev/null 2>&1; then
        snap install lxd
    else
        step "LXD snap is already installed."
    fi
    snap wait system seed.loaded || true

    step "Adding $SUDO_USER to lxd group..."
    usermod -aG lxd "${SUDO_USER:-$USER}" || true

    step "Initializing LXD (auto/minimal config)..."
    lxd init --auto
}

install_python_stack() {
    step "Updating package lists..."
    export DEBIAN_FRONTEND=noninteractive
    apt update

    step "Installing Python pip and virtual-environment packages..."
    apt install -y python3-pip python3-venv

    step "Installing host utilities, LXD prerequisites, and Python tooling..."
    apt-get update
    apt-get install -y --no-install-recommends \
        ca-certificates curl wget git \
        python3 python3-pip python3-venv python3-dev build-essential \
        lxc lxc-utils bridge-utils uidmap \
        openssh-client openssh-server \
        iproute2 iputils-ping procps net-tools dnsutils netcat-openbsd \
        jq rsync tar gzip unzip socat tmux \
        libjpeg-dev zlib1g-dev
    systemctl enable --now ssh 2>/dev/null || true

    step "Creating isolated Python virtual environment..."
    mkdir -p /root
    python3 -m venv /root/venv

    step "Activating virtual environment and installing bot dependencies..."
    # Use the virtual environment instead of installing into system Python;
    # this avoids externally-managed-environment errors on Debian/Ubuntu.
    source /root/venv/bin/activate
    python3 -m pip install --upgrade pip
    python3 -m pip install -U discord.py python-dotenv requests
    deactivate

    step "Python dependency check..."
    /root/venv/bin/python -c \
        "import discord, dotenv, requests; print('All required Python modules imported successfully.')"
}

deploy_bot() {
    step "Locating and deploying the bot source..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SOURCE_FILE=""

    if [ -f "$SCRIPT_DIR/bot.py" ]; then
        SOURCE_FILE="$SCRIPT_DIR/bot.py"
    elif [ -f "$SCRIPT_DIR/pinggy-ip.py" ]; then
        # The uploaded source may be named pinggy-ip.py; run it as bot.py.
        SOURCE_FILE="$SCRIPT_DIR/pinggy-ip.py"
        warn "bot.py not found; using pinggy-ip.py as the bot source."
    else
        err "Neither bot.py nor pinggy-ip.py was found next to install.sh."
        err "Place the bot source file in the same directory and run again."
        exit 1
    fi

    install -m 600 "$SOURCE_FILE" /root/bot.py
    /root/venv/bin/python -m py_compile /root/bot.py
    step "Bot source copied to /root/bot.py and Python syntax check passed."

    if [ -f "$SCRIPT_DIR/.env" ] && [ ! -f /root/.env ]; then
        install -m 600 "$SCRIPT_DIR/.env" /root/.env
    fi
}

configure_env() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    ENV_FILE="/root/.env"

    step "Configuring Discord bot credentials..."
    if [ -f "$SCRIPT_DIR/.env" ] && [ ! -f "$ENV_FILE" ]; then
        cp "$SCRIPT_DIR/.env" "$ENV_FILE"
    fi
    touch "$ENV_FILE"
    chmod 600 "$ENV_FILE"

    read -rsp "$(echo -e "${CYN}Enter Discord bot token: ${NC}")" DISCORD_TOKEN_INPUT
    echo
    if [ -z "$DISCORD_TOKEN_INPUT" ] || [[ "$DISCORD_TOKEN_INPUT" == *$'\\n'* ]]; then
        err "Discord bot token cannot be empty."
        exit 1
    fi

    while true; do
        read -rp "$(echo -e "${CYN}Enter Discord Admin User ID: ${NC}")" ADMIN_ID_INPUT
        if [[ "$ADMIN_ID_INPUT" =~ ^[0-9]{15,22}$ ]]; then
            break
        fi
        warn "Please enter a valid numeric Discord user ID."
    done

    while true; do
        read -rp "$(echo -e "${CYN}Enter VPS User Role ID: ${NC}")" VPS_ROLE_ID_INPUT
        if [[ "$VPS_ROLE_ID_INPUT" =~ ^[0-9]{15,22}$ ]]; then
            break
        fi
        warn "Please enter a valid numeric Discord role ID."
    done

    read -rp "$(echo -e "${CYN}Command prefix [1]: ${NC}")" PREFIX_INPUT
    PREFIX_INPUT="${PREFIX_INPUT:-1}"
    if [[ "$PREFIX_INPUT" =~ [[:space:]] ]] || [ "${#PREFIX_INPUT}" -gt 5 ] || [[ "$PREFIX_INPUT" == /* ]]; then
        err "Prefix must be 1-5 characters, without spaces, and cannot start with /."
        exit 1
    fi

    # Preserve optional settings while replacing all prompted values.
    TMP_ENV="$(mktemp)"
    grep -vE '^(DISCORD_TOKEN|MAIN_ADMIN_ID|VPS_USER_ROLE_ID|BOT_PREFIX)=' "$ENV_FILE" > "$TMP_ENV" || true
    printf 'DISCORD_TOKEN=%s\nMAIN_ADMIN_ID=%s\nVPS_USER_ROLE_ID=%s\nBOT_PREFIX=%s\n' \
        "$DISCORD_TOKEN_INPUT" "$ADMIN_ID_INPUT" "$VPS_ROLE_ID_INPUT" "$PREFIX_INPUT" >> "$TMP_ENV"
    install -m 600 "$TMP_ENV" "$ENV_FILE"
    rm -f "$TMP_ENV"
    unset DISCORD_TOKEN_INPUT

    step "Discord token, Admin ID, VPS User Role ID, and command prefix saved securely in /root/.env."
}

create_service() {
    step "Creating systemd service..."
    cat > /etc/systemd/system/bot.service <<EOF
[Unit]
Description=EVILSAAD VPS Discord Bot
Wants=network-online.target
After=network-online.target snap.lxd.daemon.service

[Service]
User=root
WorkingDirectory=/root
ExecStart=/root/venv/bin/python /root/bot.py
Restart=always
RestartSec=5
TimeoutStartSec=180
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/root/.env
Environment=BOT_NAME=EVM-V3

[Install]
WantedBy=multi-user.target
EOF

    step "Reloading systemd daemon..."
    systemctl daemon-reload

    step "Enabling bot service and starting the Discord bot automatically..."
    systemctl enable bot
    systemctl restart bot

    # Confirm the service actually started; show useful logs if startup failed.
    if systemctl is-active --quiet bot; then
        step "Discord bot is running successfully!"
    else
        err "Bot service did not start. Recent logs:"
        journalctl -u bot -n 40 --no-pager || true
        exit 1
    fi
}

final_message() {
    echo -e "\n${WHT}────────────────────────────────────────${NC}"
    echo -e "${GRN}  Installation complete!${NC}"
    echo -e "${WHT}────────────────────────────────────────${NC}"
    echo -e "  ${CYN}Service name:${NC} bot.service"
    echo -e "  ${CYN}Status:${NC}       systemctl status bot"
    echo -e "  ${CYN}Logs:${NC}         journalctl -u bot -f"
    echo -e "  ${CYN}Restart:${NC}      systemctl restart bot"
    echo -e "  ${CYN}Python env:${NC}   /root/venv"
    echo -e "  ${CYN}Bot source:${NC}   /root/bot.py"
    echo -e "${WHT}────────────────────────────────────────${NC}\n"
}

main() {
    banner
    need_root
    choose_os

    case "$OS_CHOICE" in
        1) install_lxd_ubuntu ;;
        2) install_lxd_debian ;;
        *) err "Invalid choice. Exiting."; exit 1 ;;
    esac

    install_python_stack
    deploy_bot
    configure_env
    create_service
    final_message
}

main "$@"
