#!/bin/bash
# Simple backup script
tar czf "$HOME/backup-$(date +%Y%m%d).tar.gz" "$HOME/Documents" 2>/dev/null || true
