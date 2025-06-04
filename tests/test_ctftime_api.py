#!/usr/bin/env python3
"""
Test script for CTFtime API functionality.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from ctftime_api import CTFTimeClient


async def test_ctftime_api():
    """Test CTFtime API functionality."""
    print("Testing CTFtime API...")

    try:
        client = CTFTimeClient()

        # Calculate date range for next 2 weeks
        jst = timezone(timedelta(hours=+9))
        now = datetime.now(jst)
        start_date = now
        end_date = now + timedelta(weeks=2)

        print(
            "Fetching events from "
            f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        )

        # Fetch events
        events = await client.get_events_information(
            start=start_date,
            end=end_date,
            limit=5,  # Limit to 5 events for testing
        )

        print(f"Found {len(events)} events:")

        for i, event in enumerate(events, 1):
            print(f"\n{i}. {event.title}")
            print(f"   Start: {event.start}")
            print(f"   End: {event.finish}")
            print(f"   URL: {event.ctftime_url}")

        await client.close()
        print("\nCTFtime API test completed successfully!")

    except Exception as e:
        print(f"Error testing CTFtime API: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_ctftime_api())
