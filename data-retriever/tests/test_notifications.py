"""
Unit tests for the notification module.

Tests template rendering, Discord embed conversion, and configuration loading.
"""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notifications.types import MessageField, NormalizedMessage, DiscordEmbed
from notifications.templates import (
    MessageTemplate,
    FieldTemplate,
    Colors,
    get_template,
    list_event_types,
    CHANNEL_TRADE_EXECUTIONS,
    CHANNEL_TRADE_OPPORTUNITIES,
    CHANNEL_SYSTEM_STATUS,
)
from notifications.renderer import (
    validate_required_fields,
    get_missing_fields,
    safe_format,
    render_field,
    render_template,
)
from notifications.discord_sender import to_discord_embed, build_webhook_payload
from notifications.config import (
    NotificationConfig,
    load_config_from_env,
    CHANNEL_TRADE_EXECUTIONS as CFG_CHANNEL_TRADE_EXECUTIONS,
    CHANNEL_TRADE_FAILURES,
)
from notifications.manager import NotificationManager


class TestTypes(unittest.TestCase):
    """Tests for type definitions."""
    
    def test_message_field_creation(self):
        field = MessageField(name="Symbol", value="EURUSD", inline=True)
        self.assertEqual(field.name, "Symbol")
        self.assertEqual(field.value, "EURUSD")
        self.assertTrue(field.inline)
    
    def test_normalized_message_creation(self):
        msg = NormalizedMessage(
            title="Test",
            description="Description",
            color=Colors.SUCCESS,
        )
        self.assertEqual(msg.title, "Test")
        self.assertEqual(msg.color, Colors.SUCCESS)
        self.assertEqual(msg.fields, [])
    
    def test_discord_embed_to_dict(self):
        embed = DiscordEmbed(
            title="Test",
            description="Desc",
            color=0x00FF00,
            fields=[{"name": "F1", "value": "V1", "inline": True}],
        )
        result = embed.to_dict()
        self.assertEqual(result["title"], "Test")
        self.assertEqual(result["color"], 0x00FF00)
        self.assertEqual(len(result["fields"]), 1)


class TestTemplates(unittest.TestCase):
    """Tests for template registry."""
    
    def test_get_template_signal_detected(self):
        template = get_template("signal_detected")
        self.assertIsNotNone(template)
        self.assertIn("symbol", template.required_fields)
        self.assertEqual(template.channel, CHANNEL_TRADE_OPPORTUNITIES)
    
    def test_get_template_trade_opened(self):
        template = get_template("trade_opened")
        self.assertIsNotNone(template)
        self.assertEqual(template.channel, CHANNEL_TRADE_EXECUTIONS)
    
    def test_get_template_system_startup(self):
        template = get_template("system_startup")
        self.assertIsNotNone(template)
        self.assertEqual(template.channel, CHANNEL_SYSTEM_STATUS)
    
    def test_get_template_unknown_returns_none(self):
        template = get_template("unknown_event_type")
        self.assertIsNone(template)
    
    def test_list_event_types(self):
        types = list_event_types()
        self.assertIn("signal_detected", types)
        self.assertIn("trade_opened", types)
        self.assertIn("trade_failed", types)
        self.assertIn("system_startup", types)
        self.assertIn("critical_shutdown", types)


class TestRenderer(unittest.TestCase):
    """Tests for template rendering."""
    
    def test_validate_required_fields_success(self):
        template = MessageTemplate(
            title_pattern="{symbol}",
            description_pattern="test",
            color=Colors.INFO,
            channel="test_channel",
            required_fields=["symbol", "direction"],
        )
        payload = {"symbol": "EURUSD", "direction": "BUY"}
        self.assertTrue(validate_required_fields(template, payload))
    
    def test_validate_required_fields_missing(self):
        template = MessageTemplate(
            title_pattern="{symbol}",
            description_pattern="test",
            color=Colors.INFO,
            channel="test_channel",
            required_fields=["symbol", "direction"],
        )
        payload = {"symbol": "EURUSD"}
        self.assertFalse(validate_required_fields(template, payload))
    
    def test_get_missing_fields(self):
        template = MessageTemplate(
            title_pattern="{symbol}",
            description_pattern="test",
            color=Colors.INFO,
            channel="test_channel",
            required_fields=["symbol", "direction", "timeframe"],
        )
        payload = {"symbol": "EURUSD"}
        missing = get_missing_fields(template, payload)
        self.assertEqual(set(missing), {"direction", "timeframe"})
    
    def test_safe_format_success(self):
        result = safe_format("Signal: {symbol} - {direction}", {
            "symbol": "EURUSD",
            "direction": "BUY",
        })
        self.assertEqual(result, "Signal: EURUSD - BUY")
    
    def test_safe_format_missing_key(self):
        result = safe_format("Signal: {symbol} - {direction}", {
            "symbol": "EURUSD",
        })
        self.assertEqual(result, "Signal: EURUSD - N/A")
    
    def test_render_field_with_value(self):
        ft = FieldTemplate(name="Symbol", value_key="symbol")
        field = render_field(ft, {"symbol": "GBPUSD"})
        self.assertEqual(field.name, "Symbol")
        self.assertEqual(field.value, "GBPUSD")
    
    def test_render_field_with_default(self):
        ft = FieldTemplate(name="Score", value_key="score", default="0.0")
        field = render_field(ft, {})
        self.assertEqual(field.value, "0.0")
    
    def test_render_template(self):
        template = MessageTemplate(
            title_pattern="Signal: {symbol}",
            description_pattern="{direction} on {timeframe}",
            color=Colors.SIGNAL,
            channel="test_channel",
            required_fields=["symbol", "direction", "timeframe"],
            field_templates=[
                FieldTemplate("Symbol", "symbol"),
            ],
        )
        payload = {"symbol": "EURUSD", "direction": "BUY", "timeframe": "1H"}
        msg = render_template(template, payload)
        
        self.assertEqual(msg.title, "Signal: EURUSD")
        self.assertEqual(msg.description, "BUY on 1H")
        self.assertEqual(msg.color, Colors.SIGNAL)
        self.assertEqual(len(msg.fields), 1)


class TestDiscordSender(unittest.TestCase):
    """Tests for Discord sender."""
    
    def test_to_discord_embed(self):
        msg = NormalizedMessage(
            title="Test Title",
            description="Test Desc",
            color=Colors.SUCCESS,
            fields=[MessageField("F1", "V1", True)],
            timestamp=datetime(2026, 1, 30, 12, 0, 0, tzinfo=timezone.utc),
            footer="Test Footer",
        )
        embed = to_discord_embed(msg)
        
        self.assertEqual(embed.title, "Test Title")
        self.assertEqual(embed.color, Colors.SUCCESS)
        self.assertEqual(len(embed.fields), 1)
        self.assertIsNotNone(embed.timestamp)
        self.assertEqual(embed.footer, {"text": "Test Footer"})
    
    def test_build_webhook_payload(self):
        embed = DiscordEmbed(
            title="Test",
            description="Desc",
            color=Colors.INFO,
        )
        payload = build_webhook_payload(embed)
        
        self.assertIn("embeds", payload)
        self.assertEqual(len(payload["embeds"]), 1)
        self.assertEqual(payload["embeds"][0]["title"], "Test")


class TestConfig(unittest.TestCase):
    """Tests for configuration loading."""
    
    def test_config_is_valid(self):
        config = NotificationConfig(
            webhook_urls={CFG_CHANNEL_TRADE_EXECUTIONS: "https://webhook.url"},
            enabled=True,
        )
        self.assertTrue(config.is_valid())
    
    def test_config_not_valid_disabled(self):
        config = NotificationConfig(
            webhook_urls={CFG_CHANNEL_TRADE_EXECUTIONS: "https://webhook.url"},
            enabled=False,
        )
        self.assertFalse(config.is_valid())
    
    def test_config_not_valid_no_urls(self):
        config = NotificationConfig(webhook_urls={}, enabled=True)
        self.assertFalse(config.is_valid())
    
    def test_get_webhook_url_returns_correct_url(self):
        config = NotificationConfig(
            webhook_urls={
                CFG_CHANNEL_TRADE_EXECUTIONS: "https://exec.url",
                CHANNEL_TRADE_FAILURES: "https://fail.url",
            },
            enabled=True,
        )
        self.assertEqual(config.get_webhook_url(CFG_CHANNEL_TRADE_EXECUTIONS), "https://exec.url")
        self.assertEqual(config.get_webhook_url(CHANNEL_TRADE_FAILURES), "https://fail.url")
        self.assertIsNone(config.get_webhook_url("unknown_channel"))
    
    @patch.dict(os.environ, {
        "DISCORD_WEBHOOK_TRADE_EXECUTIONS": "https://exec.url",
        "DISCORD_WEBHOOK_SYSTEM_STATUS": "https://status.url",
        "DISCORD_WEBHOOK_TIMEOUT": "10.0",
        "NOTIFICATIONS_ENABLED": "true",
    })
    def test_load_config_from_env(self):
        config = load_config_from_env()
        self.assertEqual(config.get_webhook_url("trade_executions"), "https://exec.url")
        self.assertEqual(config.get_webhook_url("system_status"), "https://status.url")
        self.assertEqual(config.timeout, 10.0)
        self.assertTrue(config.enabled)


class TestNotificationManager(unittest.TestCase):
    """Tests for NotificationManager."""
    
    def test_notify_disabled_does_not_send(self):
        config = NotificationConfig(webhook_urls={}, enabled=False)
        manager = NotificationManager(config)
        
        # Should not raise
        manager.notify("signal_detected", {"symbol": "EURUSD"})
    
    @patch("notifications.manager.send_message")
    def test_notify_sends_to_correct_channel(self, mock_send):
        mock_send.return_value = True
        
        config = NotificationConfig(
            webhook_urls={
                "trade_opportunities": "https://opportunities.url",
            },
            enabled=True,
        )
        manager = NotificationManager(config)
        
        manager.notify("signal_detected", {
            "symbol": "EURUSD",
            "direction": "BUY",
            "signal_time": "2026-01-30 09:00",
            "entry_price": "1.08500",
            "sl_price": "1.08300",
            "tp_price": "1.08900",
            "lot_size": "0.10",
            "aoi_range": "1.08400 - 1.08600",
            "aoi_timeframe": "1H",
            "score": "4.5",
        })
        
        mock_send.assert_called_once()
        # Verify webhook URL
        call_args = mock_send.call_args
        self.assertEqual(call_args[0][0], "https://opportunities.url")
    
    def test_is_enabled_property(self):
        config = NotificationConfig(
            webhook_urls={"trade_executions": "https://test.url"},
            enabled=True,
        )
        manager = NotificationManager(config)
        self.assertTrue(manager.is_enabled)


if __name__ == "__main__":
    unittest.main()
