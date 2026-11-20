# 0.6.0 (B1): placeholder. live-config's xinit component writes this file to
# run "while true; do startx; done" for any login on tty1, which took over the
# Terminal-mode console (input stopped after a few commands). An existing file
# makes that component skip; the build also removes the component. StickLLM
# starts its desktop only from stickllm-kiosk.service, never from a login.
:
