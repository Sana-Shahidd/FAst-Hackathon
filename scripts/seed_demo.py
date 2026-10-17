"""Seed a demo reader for the recording: python -m scripts.seed_demo --email demo@subah.app --password '...'

Run it yourself against the project in your `.env` (it creates one auth user with the service-role
key). It onboards the reader (English edition, 6 topics, Lahore, two favorite outlets, one muted word),
prints the last three days' papers with the real feeds and models, then reacts to stories so the
profile already shows movement and one learned suggestion is waiting.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from app import deps
from app.models import OnboardingData, TopicChoice
from app.services import edition, learning, onboarding, reading

TOPICS = {
    "ai": 1.0,
    "startups": 0.7,
    "pakistan": 0.7,
    "sports_cricket": 0.7,
    "climate": 0.4,
    "technology": 0.4,
}


async def main(email: str, password: str, days: int) -> None:
    admin = deps.supabase_admin()
    made = admin.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    )
    user_id = str(made.user.id)
    data = OnboardingData(
        edition_lang="en",
        topics=[TopicChoice(key=k, weight=w) for k, w in TOPICS.items()],
        display_name="Demo Reader",
        city="Lahore",
        timezone="Asia/Karachi",
        reading_minutes=10,
        favorite_sources=["bbc"],
        muted_keywords=["celebrity gossip"],
    )
    await onboarding.save_onboarding(user_id, data, email)
    profile = await edition.get_profile(user_id)
    today = edition.local_date_for(profile.timezone)
    edition_ids = []
    for offset in range(days - 1, -1, -1):
        edition_id = await edition.generate_edition(
            user_id, today - timedelta(days=offset)
        )
        edition_ids.append(edition_id)
        print(f"printed {today - timedelta(days=offset)} -> {edition_id}")
    stories = await reading.edition_articles(edition_ids[0])
    for story in stories[1:7]:
        await reading.record_signal(user_id, story["id"], "more_like", once=True)
    await learning.maybe_run_learner(user_id, edition_ids[-1])
    print(f"done: sign in as {email}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--days", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(main(args.email, args.password, args.days))
