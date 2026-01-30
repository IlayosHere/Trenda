"""
Template rendering logic.

Converts templates and payloads into normalized message structures.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from .types import MessageField, NormalizedMessage
from .templates import MessageTemplate, FieldTemplate


def validate_required_fields(template: MessageTemplate, payload: Dict) -> bool:
    """
    Check if payload contains all required fields for the template.
    
    Args:
        template: The message template
        payload: The payload dictionary
        
    Returns:
        True if all required fields are present, False otherwise
    """
    for field_key in template.required_fields:
        if field_key not in payload:
            return False
    return True


def get_missing_fields(template: MessageTemplate, payload: Dict) -> List[str]:
    """
    Get list of missing required fields.
    
    Args:
        template: The message template
        payload: The payload dictionary
        
    Returns:
        List of missing field names
    """
    return [f for f in template.required_fields if f not in payload]


def safe_format(pattern: str, payload: Dict) -> str:
    """
    Safely format a pattern string with payload values.
    
    Missing keys are replaced with 'N/A' instead of raising errors.
    
    Args:
        pattern: Format string with {key} placeholders
        payload: Dictionary of values
        
    Returns:
        Formatted string with values substituted
    """
    try:
        return pattern.format(**payload)
    except KeyError:
        # Fallback: replace missing keys with N/A
        result = pattern
        import re
        for match in re.finditer(r'\{(\w+)\}', pattern):
            key = match.group(1)
            value = payload.get(key, 'N/A')
            result = result.replace(f'{{{key}}}', str(value))
        return result


def render_field(field_template: FieldTemplate, payload: Dict) -> MessageField:
    """
    Render a single field template with payload data.
    
    Args:
        field_template: The field template
        payload: The payload dictionary
        
    Returns:
        Rendered MessageField
    """
    value = payload.get(field_template.value_key)
    if value is None:
        value = field_template.default if field_template.default else "N/A"
    
    return MessageField(
        name=field_template.name,
        value=str(value),
        inline=field_template.inline,
    )


def render_fields(
    field_templates: List[FieldTemplate],
    payload: Dict
) -> List[MessageField]:
    """
    Render all field templates with payload data.
    
    Args:
        field_templates: List of field templates
        payload: The payload dictionary
        
    Returns:
        List of rendered MessageFields
    """
    return [render_field(ft, payload) for ft in field_templates]


def render_template(
    template: MessageTemplate,
    payload: Dict,
    timestamp: Optional[datetime] = None,
    footer: Optional[str] = None,
) -> NormalizedMessage:
    """
    Render a template with payload data into a normalized message.
    
    Args:
        template: The message template
        payload: Dictionary of values to render into the template
        timestamp: Optional timestamp (defaults to current UTC time)
        footer: Optional footer text
        
    Returns:
        Rendered NormalizedMessage
    """
    title = safe_format(template.title_pattern, payload)
    description = safe_format(template.description_pattern, payload)
    fields = render_fields(template.field_templates, payload)
    
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    
    return NormalizedMessage(
        title=title,
        description=description,
        color=template.color,
        fields=fields,
        timestamp=timestamp,
        footer=footer,
    )
