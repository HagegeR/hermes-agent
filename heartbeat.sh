#!/bin/bash
# Rate limit watchdog — heartbeat every 5 minutes
# If this stops arriving, the agent hit a rate limit or context compaction
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Agent heartbeat — still alive and working"