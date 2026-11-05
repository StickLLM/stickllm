# 0.6.1: Terminal mode console (tty1 autologin). Short banner without secrets;
# F10 shows the SSH password, F9 the pair code (stickllm-show-secrets).
case "$-" in *i*) ;; *) return 0 2>/dev/null || exit 0 ;; esac
if [ -n "${BASH_VERSION:-}" ] && grep -qw 'stickllm.ssh' /proc/cmdline 2>/dev/null; then
  bind -x '"\e[21~": /usr/local/bin/stickllm-show-secrets ssh' 2>/dev/null
  bind -x '"\e[20~": /usr/local/bin/stickllm-show-secrets pair' 2>/dev/null
  if [ "$(tty 2>/dev/null)" = "/dev/tty1" ] && [ -z "${STICKLLM_TERM_BANNER_DONE:-}" ]; then
    export STICKLLM_TERM_BANNER_DONE=1
    _ip="$(/usr/local/bin/stickllm-lan-ip 2>/dev/null | tr -d '[:space:]')"
    printf '\n  StickLLM Terminal - root console\n'
    printf '  LAN IP:  %s\n' "${_ip:-waiting for the network (stickllm-wifi-setup for WiFi)}"
    printf '  SSH:     ssh stickllm@%s\n' "${_ip:-<lan-ip>}"
    printf '  F10 = show SSH password   F9 = pair code   stickllm-status = health\n\n'
    unset _ip
  fi
fi
