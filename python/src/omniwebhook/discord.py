"""El esquema de firma de Discord. Necesita `omniwebhook[ed25519]`."""

from omniwebhook.adapters.schemes.discord import discord_scheme

__all__ = ["discord_scheme"]
