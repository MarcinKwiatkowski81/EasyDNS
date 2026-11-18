# 🚀 API-Key Quick Start Guide

## 5-Minute Setup

### 1. Generate Your API Key

```bash
openssl rand -hex 16 | sed 's/^/sk-/'
# Output: sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

Copy the generated key - you'll need it in the next step.

### 2. Add to Configuration

Edit `config.yaml`:

```yaml
api:
  enabled: true
  listen: "0.0.0.0"
  port: 8080
  keys:
    - "sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"  # Your key here
```

### 3. Start the Server

```bash
python3 -m dns_server -c config.yaml
```

### 4. Test It Works

```bash
# Replace with your actual key
curl -H "X-API-Key: sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6" \
  http://localhost:8080/api/v1/health

# Expected output:
# {"status": "ok"}
```

✅ You're done! API is now secured with API-Key authentication.

---

## Common Tasks

### How to Use in Different Languages

#### Bash/curl

```bash
API_KEY="sk-your-key-here"

# List zones
curl -H "X-API-Key: $API_KEY" https://api.example.com/api/v1/zones

# Add record
curl -X POST https://api.example.com/api/v1/zones/example.com/records \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"www","type":"A","ttl":300,"rdata":{"value":"1.2.3.4"}}'
```

#### Python

```python
import requests

API_KEY = "sk-your-key-here"
headers = {"X-API-Key": API_KEY}

# List zones
response = requests.get(
    "https://api.example.com/api/v1/zones",
    headers=headers
)
print(response.json())
```

#### Node.js / JavaScript

```javascript
const API_KEY = "sk-your-key-here";

fetch("https://api.example.com/api/v1/zones", {
  headers: { "X-API-Key": API_KEY }
})
.then(r => r.json())
.then(data => console.log(data));
```

---

## Troubleshooting

### "401 Unauthorized"

This means your API key is wrong or missing.

**Solution:**
1. Check if `api.keys` is set in config.yaml
2. Check if you're sending the header:
   ```bash
   curl -v -H "X-API-Key: sk-..." https://...
   ```
3. Make sure your key matches exactly (copy-paste to avoid typos)

### "403 Forbidden"

This means your API key is correct, but your IP doesn't have API permission in ACL.

**Solution:**
1. Check `config.yaml` ACL section
2. Make sure your IP has `"api"` permission:
   ```yaml
   acl:
     - name: "my-network"
       match: ["192.168.1.0/24"]
       allow: ["api"]
   ```

### "429 Too Many Requests"

You've exceeded the rate limit (10 requests per 60 seconds).

**Solution:**
- Wait 60 seconds and try again
- Space out your requests if you need more

---

## Multiple Keys for Different Environments

```yaml
api:
  keys:
    - "sk-prod-1234567890abcdef"       # Production
    - "sk-staging-fedcba0987654321"    # Staging
    - "sk-dev-abcdef1234567890"        # Development
```

Each key works independently. Any valid key grants access.

---

## Rotating Keys

Need to change your API key?

1. Add new key to `config.yaml`:
   ```yaml
   api:
     keys:
       - "sk-prod-old-key"              # Old key (temporary)
       - "sk-prod-new-key"              # New key
   ```

2. Restart server:
   ```bash
   systemctl restart easydns
   ```

3. Update all clients to use new key

4. Remove old key from config:
   ```yaml
   api:
     keys:
       - "sk-prod-new-key"              # Only new key
   ```

5. Restart server again

---

## Header Format Options

All these formats work:

```bash
# Option 1 (Recommended)
curl -H "X-API-Key: sk-..." https://...

# Option 2
curl -H "Authorization: Bearer sk-..." https://...

# Option 3
curl -H "Authorization: sk-..." https://...
```

---

## Real-World Example

**Scenario:** Monitor your DNS server with a monitoring script

```bash
#!/bin/bash
API_KEY="sk-prod-monitoring"
API_URL="https://dns.example.com:8443/api/v1"

# Check health
health=$(curl -s -H "X-API-Key: $API_KEY" "$API_URL/health")
status=$(echo "$health" | grep -o '"status":"ok"')

if [ -z "$status" ]; then
    echo "ERROR: DNS API is down!"
    exit 1
fi

# Get stats
stats=$(curl -s -H "X-API-Key: $API_KEY" "$API_URL/stats")
zones=$(echo "$stats" | grep -o '"zones_count":[0-9]*')
echo "✓ DNS API OK ($zones)"
```

---

## Security Best Practices

✅ **DO:**
- Use strong, random keys (use the generation command above)
- Store keys in secure config file (permissions 0640)
- Use HTTPS in production
- Rotate keys every 90 days
- Monitor for failed API-Key attempts
- Use different keys for different services

❌ **DON'T:**
- Commit API keys to Git
- Use simple/predictable keys
- Share keys between environments
- Hardcode keys in scripts (use env vars)
- Reuse old keys

---

## Next Steps

- 📖 Read [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for full API reference
- 🔐 Read [API_KEY_GUIDE.md](API_KEY_GUIDE.md) for detailed security info
- 📚 Read [API_SETUP_GUIDE.md](API_SETUP_GUIDE.md) for advanced configuration

---

**Need help?** Check the [API_KEY_GUIDE.md](API_KEY_GUIDE.md) troubleshooting section.
