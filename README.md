# Webcam Light Controller for macOS

A Python application that monitors macOS camera usage in real-time and sends webhook notifications when the camera activates. Designed to integrate with home automation systems like Home Assistant.

## Overview

This script automatically detects when your Mac's webcam turns on and triggers webhook notifications to control smart home devices. The primary use case is automatically turning on a desk lamp when the webcam activates to improve lighting for video calls.

## Webhook Triggering Conditions

The webhook will **only** be sent when the camera activates AND the following conditions are met:

**Home Network Detection**\
This feature ensures notifications only happen when you're at your home office. The system checks if any of your Mac's IP addresses start with the configured `HOME_IP_PREFIX` (default: `192.168.137.`). You can disable this check by setting `REQUIRE_HOME_NETWORK="false"`.

**External Monitor Detection**\
This assumes you only want desk lighting when using an external monitor setup. The system uses `system_profiler` to detect connected external displays. You can disable this check by setting `REQUIRE_EXTERNAL_MONITOR="false"`.

These conditions prevent unwanted automations when working away from your home office setup.

## Example Use Cases

### 1. Desk Lamp Automation

This script automatically turns on a desk lamp when the webcam activates, improving lighting for video calls. When the camera turns on, Home Assistant receives a webhook notification and triggers an automation to turn on the desk lamp, making the webcam picture look better with proper lighting.

### 2. Busy Light Indicator

When the camera activates during a meeting, Home Assistant can turn on a "busy light" (like a smart bulb or LED strip) visible to family members, signaling that you're in a meeting and don't want to be disturbed.

## How It Works

1. Camera Monitoring: Uses macOS system logs to detect camera state changes
2. Condition Checking: Validates network location and external monitor presence
3. Webhook Notifications: Sends HTTP POST requests to your home automation system
4. Smart Debouncing: Prevents duplicate notifications within a configurable time window

## Requirements

- macOS (uses system-specific commands)
- Python 3.6+
- No additional packages required (uses standard library only)

## Installation

1. Clone or download the script
2. No additional dependencies needed - uses Python standard library

## Configuration

The application reads configuration from environment variables. You can set these in your shell or use a process manager like systemd or launchd.

### Environment Variables

```bash
# Webhook configuration
export WEBHOOK_URL="http://homeassistant:8123/api/webhook/your-webhook-id"

# Network and hardware requirements
export HOME_IP_PREFIX="192.168.137."
export REQUIRE_HOME_NETWORK="true"
export REQUIRE_EXTERNAL_MONITOR="true"

# Timing configuration
export DEBOUNCE_SECONDS="5.0"
export DISPLAYS_CACHE_TTL_SECONDS="15"
```

### Configuration Options

| Variable                     | Default                                                 | Description                                             |
|------------------------------|---------------------------------------------------------|---------------------------------------------------------|
| `WEBHOOK_URL`                | `http://homeassistant:8123/api/webhook/your-webhook-id` | Complete webhook URL including endpoint                 |
| `HOME_IP_PREFIX`             | `192.168.137.`                                          | IP prefix to identify home network                      |
| `REQUIRE_HOME_NETWORK`       | `true`                                                  | Only send notifications when on home network            |
| `REQUIRE_EXTERNAL_MONITOR`   | `true`                                                  | Only send notifications when external monitor connected |
| `DEBOUNCE_SECONDS`           | `5.0`                                                   | Minimum time between duplicate notifications            |
| `DISPLAYS_CACHE_TTL_SECONDS` | `15`                                                    | How long to cache external monitor detection            |
| `COMMAND_TIMEOUT`            | `6`                                                     | Timeout for system commands (in seconds)                |
| `DETECT_MONITOR_TIMEOUT`     | `6`                                                     | Timeout for monitor detection (in seconds)              |

### Command Line Arguments

You can also override configuration using command line arguments:

```bash
# Set complete webhook URL
python3 webcam_light.py --webhook-url http://homeassistant:8123/api/webhook/your-webhook-id

# Override network requirements
python3 webcam_light.py --no-require-home-network --no-require-external-monitor --webhook-url http://homeassistant:8123/api/webhook/your-webhook-id
```

**Note**: Command line arguments take precedence over environment variables.

## Usage

Run the script directly:

```bash
python3 webcam_light.py --webhook-url http://homeassistant:8123/api/webhook/your-webhook-id
```

Or make it executable:

```bash
chmod +x webcam_light.py
./webcam_light.py --webhook-url http://homeassistant:8123/api/webhook/your-webhook-id
```

## Webhook Payload

When the camera turns on and conditions are met, a POST request is sent with this JSON structure:

```json
{
  "state": "on",
  "home_network": true,
  "ip_addresses": ["192.168.137.123"],
  "external_monitor": true
}
```

## Home Assistant Integration

### Setting Up the Webhook

1. Create a webhook automation in Home Assistant
2. Create an automation that responds to the webhook to control your lights

### Example Home Assistant Automation

```yaml
alias: "Webhook: turn on/off desk lamp"
description: "POST JSON: {\"state\":\"on\"} or {\"state\":\"off\"}"
triggers:
  - trigger: webhook
    webhook_id: your-webhook-id
    allowed_methods:
      - POST
    local_only: true
conditions: []
actions:
  - choose:
      - conditions:
          - condition: template
            value_template: "{{ st == 'on' }}"
        sequence:
          - action: light.turn_on
            target:
              entity_id: light.schreibtischlampe_edy
            data:
              brightness_pct: 100
              transition: 1
      - conditions:
          - condition: template
            value_template: "{{ st == 'off' }}"
        sequence:
          - action: light.turn_off
            target:
              entity_id: light.schreibtischlampe_edy
            data:
              transition: 1
variables:
  st: "{{ (trigger.json | default({}, true)).state | default('', true) | lower }}"
mode: restart
```

**Important**: Replace `your-webhook-id` with your actual webhook ID, and update the `entity_id` to match your specific light entity in Home Assistant.

## AI Development Note

This project was heavily created using AI assistance as a learning exercise to:
- Understand how to effectively collaborate with AI tools
- Improve AI prompting and interaction skills
- Explore AI-assisted development workflows

