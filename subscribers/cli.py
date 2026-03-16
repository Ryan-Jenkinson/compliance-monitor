#!/usr/bin/env python3
"""Subscriber management CLI.

Usage:
    python subscribers/cli.py add --email you@example.com --name Ryan
    python subscribers/cli.py remove --email you@example.com
    python subscribers/cli.py list
    python subscribers/cli.py set-pref --email you@example.com --topic PFAS --enable
    python subscribers/cli.py set-pref --email you@example.com --topic REACH --disable
"""
import sys
from pathlib import Path

# Allow running as a script from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import click

from subscribers.db import init_db
from subscribers.repository import SubscriberRepository

repo = SubscriberRepository()


@click.group()
def cli():
    """Manage compliance newsletter subscribers."""
    init_db()


@cli.command()
@click.option("--email", required=True, help="Subscriber email address")
@click.option("--name", required=True, help="Subscriber first name")
def add(email: str, name: str):
    """Add a new subscriber (all topics enabled by default)."""
    existing = repo.get_by_email(email)
    if existing:
        click.echo(f"Subscriber {email} already exists (id={existing.id}, active={existing.is_active})")
        return

    sub = repo.add(email, name)
    click.echo(f"Added subscriber: {sub.first_name} <{sub.email}> (id={sub.id})")
    click.echo("Enabled topics: PFAS, EPR, REACH, TSCA")


@cli.command()
@click.option("--email", required=True, help="Subscriber email address")
def remove(email: str):
    """Deactivate a subscriber (soft delete)."""
    if repo.remove(email):
        click.echo(f"Deactivated: {email}")
    else:
        click.echo(f"Not found: {email}", err=True)
        sys.exit(1)


@cli.command("list")
def list_subscribers():
    """List all active subscribers."""
    subs = repo.list_active()
    if not subs:
        click.echo("No active subscribers.")
        return

    click.echo(f"{'ID':<6} {'Name':<20} {'Email':<35} {'Topics'}")
    click.echo("-" * 80)
    for sub in subs:
        topics = ", ".join(repo.get_enabled_topics(sub.id))
        click.echo(f"{sub.id:<6} {sub.first_name:<20} {sub.email:<35} {topics}")


@cli.command("set-pref")
@click.option("--email", required=True, help="Subscriber email")
@click.option("--topic", required=True, type=click.Choice(["PFAS", "EPR", "REACH", "TSCA"]))
@click.option("--enable/--disable", default=True)
def set_pref(email: str, topic: str, enable: bool):
    """Enable or disable a topic for a subscriber."""
    sub = repo.get_by_email(email)
    if not sub:
        click.echo(f"Subscriber not found: {email}", err=True)
        sys.exit(1)

    repo.set_topic(sub.id, topic, enable)
    state = "enabled" if enable else "disabled"
    click.echo(f"Topic {topic} {state} for {email}")


if __name__ == "__main__":
    cli()
