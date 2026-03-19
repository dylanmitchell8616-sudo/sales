# Realside AI Sales Pipeline — Project Memory

## Key Context
- **Company:** Realside AI — AI Employees for service businesses (med spas, dental, wellness)
- **Products:** AI Inbound Receptionist + AI Outbound Agent
- **Pricing:** Starts at $2K/month, custom based on volume
- **Calendar:** https://calendly.com/realsideai
- **Sender:** Dylan Mitchell (dylan.realside@gmail.com)

## Objection Handling Framework (Imperium Method)
- All objection responses must: empathize first, reframe with logic/social proof, end with low-friction CTA
- Keep all responses under 120 words unless otherwise asked
- Never use '--' in messaging
- Tone: friendly, confident, value-driven — never robotic or overly formal
- Always spark curiosity to drive toward a call, don't answer questions fully over email

### Reply Categories (Instantly Tags)
- **Not Interested**: Tag in Instantly, do not re-email. Never reply to hostile/rude messages.
- **Interested**: Anything not directly negative. Tag as interested, add to engaged prospect tracker.
- **Meeting Booked**: Tag as booked, send booking confirmation, highlight green in tracker.

### Reply Flow (Multi-Channel, after interested reply)
1. Send email reply
2. Label in Instantly
3. Add to engaged prospect tracker
4. Call them immediately
5. Double-dial if no answer
6. WhatsApp voice note
7. Text if no WhatsApp
8. LinkedIn connect + message
9. Facebook friend + DM if no LinkedIn
10. Twitter/Instagram follow + DM as last resort

### Objection Types & Strategies
- **Direct Intent** → Send Calendly link immediately
- **"How does it work?"** → Redirect to call — "best explained on a demo"
- **"How much?"** → First: deflect to call. If pressed: anchor price ($2K/mo) to result (40 pre-qualified appointments)
- **"Send proof"** → Offer to walk through case studies on a demo call
- **"Not interested" / "Tried before"** → Record 60-second Loom to break the pattern
- **"Already have someone"** → Acknowledge, highlight differentiation on a call

### Engaged Follow-Up Process
- Follow up once per day, 8 attempts max
- Each follow-up adds new value (case study, insight, social proof)
- After 8 with no reply → tag "Not Interested", highlight red
- When they book → tag "Booked", highlight green

## Reply Autopilot (Fully Automated)
- `reply_autopilot.py` is a daemon that polls Instantly's API for new replies every 60 seconds
- Classifies each reply with Claude (direct_intent, how_does_it_work, how_much, send_proof, not_interested, tried_before, already_have, timing, positive_other, negative_other)
- Auto-tags leads in Instantly (Interested, Not Interested, Meeting Booked)
- Generates and sends AI responses back through Instantly API for all positive/curious replies
- Skips hostile/rude replies entirely
- Tracks processed replies in output/processed_replies.json to avoid double-processing
- Logs everything to output/reply_autopilot.log
- Run with: `python reply_autopilot.py` or `./run_reply_autopilot.sh --foreground`
- Supports `--dry-run` (classify + generate but don't send) and `--once` (single pass, no loop)
- NO manual CSV exports needed — everything flows through the Instantly API

## Pipeline Architecture
- Scripts generate personalized emails → CSVs → uploaded to Instantly.ai as draft campaigns
- Campaign types: Prospect Outreach, Case Study Match, News Trigger, Competitor Displacement, Social Warm Outreach, Job Signal, Event Outreach, Follow-up Sequences, Objection Responses, Engaged Follow-ups
- All campaigns created in DRAFT mode — manual activation required
- Sending schedule: 7-9 AM + 1-3 PM Mon-Fri (America/Chicago), 30/day limit per account
- Reply management is fully automated via reply_autopilot.py (no manual steps)

## ZoomInfo API
- When user provides ZoomInfo API key, configure it but DO NOT use any credits for testing
- Only use credits during actual pipeline runs for real lead sourcing

## Important Files
- `config.json` — Master config (API keys, sender info, ICP, campaign settings)
- `sales_playbook.md` — Full objection handling scripts and reply management SOPs
- `instantly_uploader.py` — Uploads CSVs to Instantly.ai campaigns
- `objection_handler.py` — AI-powered objection response generator
- `engaged_followup_generator.py` — 8-touch warm follow-up sequence generator
- `followup_generator.py` — 4-touch cold follow-up sequence generator
- `reply_autopilot.py` — Fully automated reply manager daemon (polls Instantly API, classifies, responds, tags)
- `run_reply_autopilot.sh` — Shell runner for reply autopilot daemon
- `meeting_prep.py` — Auto-generates meeting prep briefs for hot leads (scrapes website, emails brief to Dylan)
- `pipeline_metrics.py` — Exports pipeline metrics (reply rates, booking rates, conversion by campaign) to CSV/JSON
- `run_full_pipeline.py` — End-to-end pipeline orchestration
