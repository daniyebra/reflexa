#!/usr/bin/env bash
# Start ngrok and print the public URL once the tunnel is established.
ngrok http 8501 --log /tmp/ngrok.log &
NGROK_PID=$!

echo "Waiting for tunnel…"
for i in $(seq 1 20); do
    sleep 1
    URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null \
        | python3 -c "
import sys, json
try:
    tunnels = json.load(sys.stdin).get('tunnels', [])
    urls = [t['public_url'] for t in tunnels if 'https' in t['public_url']]
    print(urls[0] if urls else '')
except Exception:
    print('')
" 2>/dev/null)
    if [ -n "$URL" ]; then
        echo ""
        echo "  ┌──────────────────────────────────────────────────┐"
        echo "  │  Share with participants:                        │"
        echo "  │  $URL"
        echo "  └──────────────────────────────────────────────────┘"
        echo ""
        break
    fi
done

wait $NGROK_PID
