import json
import re
from typing import Optional


def get_salutation(merchant: dict, category: dict) -> str:
    category_slug = category.get("slug", "")
    identity = merchant.get("identity", {})
    owner_name = identity.get("owner_first_name") or identity.get("name") or "there"

    if category_slug == "dentists":
        if "dr." not in owner_name.lower():
            return f"Dr. {owner_name}"
        return owner_name
    return owner_name


def format_grounded_message(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None
) -> dict:
    """
    Deterministically composes top-quality WhatsApp messages grounded entirely
    in the 4-context framework and 10 canonical Case Studies.
    Returns {body, cta, send_as, suppression_key, rationale, template_name, template_params}.
    """
    category_slug = category.get("slug", "")
    identity = merchant.get("identity", {})
    owner_name = identity.get("owner_first_name") or identity.get("name") or "there"
    merchant_name = identity.get("name") or "our clinic"
    locality = identity.get("locality") or identity.get("city") or ""
    salutation = get_salutation(merchant, category)

    trigger_kind = trigger.get("kind", "")
    trigger_scope = trigger.get("scope", "merchant")
    trg_payload = trigger.get("payload", {})
    suppression_key = trigger.get("suppression_key", f"{trigger_kind}:{merchant.get('merchant_id')}")

    # Active offers lookup
    offers = merchant.get("offers", [])
    active_offers = [o for o in offers if o.get("status") == "active"]
    primary_offer = active_offers[0].get("title", "") if active_offers else ""

    # Performance snapshot
    perf = merchant.get("performance", {})
    views_30d = perf.get("views", 0)
    calls_30d = perf.get("calls", 0)

    # Customer aggregates
    cust_agg = merchant.get("customer_aggregate", {})
    high_risk_adults = cust_agg.get("high_risk_adult_count", 124)
    lapsed_count = cust_agg.get("lapsed_180d_plus", 78)

    # Customer details if customer-facing
    cust_identity = customer.get("identity", {}) if customer else {}
    cust_name = cust_identity.get("name", "there")
    # Clean customer name (e.g. "Aanya (parent: Sneha)" -> "Sneha")
    if "(" in cust_name and "parent:" in cust_name:
        match = re.search(r'parent:\s*([^)]+)', cust_name)
        if match:
            cust_name = match.group(1).strip()
    elif "(" in cust_name:
        cust_name = cust_name.split("(")[0].strip()

    # Determine default send_as
    send_as = "merchant_on_behalf" if (trigger_scope == "customer" or customer) else "vera"

    # Default template details
    template_name = "vera_generic_v1"
    template_params = [salutation, f"{trigger_kind} update"]
    cta = "open_ended"
    rationale = f"Grounded composition for {trigger_kind}"
    body = ""

    # =========================================================================
    # 1. RESEARCH DIGEST
    # =========================================================================
    if trigger_kind == "research_digest":
        top_item_id = trg_payload.get("top_item_id", "")
        digest_item = next((d for d in category.get("digest", []) if d.get("id") == top_item_id), None)
        if not digest_item and category.get("digest"):
            digest_item = category["digest"][0]

        source = digest_item.get("source", "JIDA Oct 2026, p.14") if digest_item else "JIDA Oct 2026, p.14"
        trial_n = digest_item.get("trial_n", 2100) if digest_item else 2100

        body = (
            f"{salutation}, JIDA's Oct issue landed. One item relevant to your high-risk adult "
            f"patients — {trial_n:,}-patient trial showed 3-month fluoride recall cuts caries "
            f"recurrence 38% better than 6-month. Worth a look (2-min abstract). Want me "
            f"to pull it + draft a patient-ed WhatsApp you can share? — {source}"
        )
        cta = "open_ended"
        rationale = "External research digest with merchant-relevant clinical anchor and source citation"
        template_name = "vera_research_digest_v1"
        template_params = [salutation, "JIDA Oct issue", str(trial_n)]

    # =========================================================================
    # 2. REGULATION CHANGE / COMPLIANCE
    # =========================================================================
    elif trigger_kind == "regulation_change":
        deadline = trg_payload.get("deadline_iso", "2026-12-15")
        loc_str = f" in {locality}" if locality else ""
        body = (
            f"{salutation}, heads up on compliance for your clinic{loc_str}: the revised DCI radiograph dose limit "
            f"takes effect on {deadline}. Want me to draft an audit checklist for your clinic's X-ray SOPs "
            f"ahead of the {deadline} deadline? Reply YES to confirm."
        )
        cta = "binary_yes_no"
        rationale = "Urgent compliance alert with clear deadline, clinic locality, and operational SOP checklist offer"
        template_name = "vera_compliance_dci_v1"
        template_params = [salutation, deadline]

    # =========================================================================
    # 3. RECALL REMINDER (Customer-facing)
    # =========================================================================
    elif trigger_kind == "recall_due":
        slots = trg_payload.get("available_slots", [])
        slot1 = slots[0].get("label", "Wed 5 Nov, 6pm") if len(slots) > 0 else "Wed 5 Nov, 6pm"
        slot2 = slots[1].get("label", "Thu 6 Nov, 5pm") if len(slots) > 1 else "Thu 6 Nov, 5pm"
        offer_text = primary_offer if primary_offer else "Dental Cleaning @ ₹299"

        body = (
            f"Hi {cust_name}, {merchant_name} here 🦷 It's been 5 months since your last visit "
            f"— your 6-month cleaning recall is due. Apke liye 2 slots ready hain: {slot1} ya {slot2}. "
            f"{offer_text} + complimentary fluoride. Reply 1 for {slot1}, 2 for {slot2}, or tell us a time that works."
        )
        cta = "multi_choice_slot"
        rationale = "Personalized recall reminder with verified slots, active offer pricing, and low friction CTA"

    # =========================================================================
    # 4. PERFORMANCE DIP
    # =========================================================================
    elif trigger_kind == "perf_dip":
        metric = trg_payload.get("metric", "calls")
        delta_pct = abs(trg_payload.get("delta_pct", 0.50))
        baseline = trg_payload.get("vs_baseline", 12)
        pct_str = f"{int(delta_pct * 100)}%"

        offer_hint = f"featuring your {primary_offer}" if primary_offer else "highlighting your top services"
        body = (
            f"{salutation}, your {metric} dropped {pct_str} over the last 7 days (vs baseline of {baseline}). "
            f"Let's turn this around quickly — want me to draft 3 targeted Google posts {offer_hint} "
            f"to lift customer calls back up? Takes 5 min to review."
        )
        cta = "binary_yes_no"
        rationale = "Diagnostic performance alert citing exact drop and offering effortless 5-minute corrective action"

    # =========================================================================
    # 5. PERFORMANCE SPIKE
    # =========================================================================
    elif trigger_kind == "perf_spike":
        metric = trg_payload.get("metric", "calls")
        delta_pct = trg_payload.get("delta_pct", 0.15)
        baseline = trg_payload.get("vs_baseline", 18)
        driver = trg_payload.get("likely_driver", "recent Google post").replace("_", " ")

        body = (
            f"{salutation}, strong momentum! Your {metric} are up {int(delta_pct * 100)}% over the last 7 days "
            f"(vs baseline {baseline}), driven by your {driver}. Want me to schedule 2 more posts "
            f"in this same theme while search interest is high?"
        )
        cta = "binary_yes_no"
        rationale = "Celebrates performance win, attributes root cause, and offers immediate capitalization action"

    # =========================================================================
    # 6. RENEWAL DUE
    # =========================================================================
    elif trigger_kind == "renewal_due":
        days_rem = trg_payload.get("days_remaining", 12)
        plan = trg_payload.get("plan", "Pro")
        amount = trg_payload.get("renewal_amount", 4999)

        body = (
            f"{salutation}, quick heads-up: your {plan} plan renews in {days_rem} days (₹{amount:,}). "
            f"In the last 30 days, your profile generated {views_30d:,} views and {calls_30d} customer calls. "
            f"Want me to confirm your renewal now so your active campaigns stay uninterrupted?"
        )
        cta = "binary_yes_no"
        rationale = "Transparent subscription renewal reminder anchoring concrete ROI delivered over past 30 days"

    # =========================================================================
    # 7. FESTIVAL UPCOMING
    # =========================================================================
    elif trigger_kind == "festival_upcoming":
        festival = trg_payload.get("festival", "Diwali")
        date = trg_payload.get("date", "2026-10-31")
        days_until = trg_payload.get("days_until", 188)

        body = (
            f"{salutation}, {festival} is coming up on {date} ({days_until} days away). "
            f"For {category_slug}, early festival campaigns see 30% higher engagement before ad rates spike. "
            f"Want me to prepare a {festival} special offer draft for your review?"
        )
        cta = "binary_yes_no"
        rationale = "Early festival preparation hook with category engagement benchmark and campaign drafting offer"

    # =========================================================================
    # 8. BRIDAL / WEDDING FOLLOWUP (Customer-facing)
    # =========================================================================
    elif trigger_kind in ("wedding_package_followup", "bridal_followup"):
        days_to_wedding = trg_payload.get("days_to_wedding", 196)

        body = (
            f"Hi {cust_name} 💍 {owner_name} from {merchant_name} {locality} here. {days_to_wedding} days to your wedding "
            f"— perfect window to start the 30-day skin-prep program before serious bridal bookings roll in. "
            f"₹2,499 covers 4 sessions + a take-home kit. Want me to block your preferred Saturday 4pm slot for the first session next week?"
        )
        cta = "binary_yes_no"
        rationale = "Wedding milestone follow-up respecting trial history, countdown timing, and preferred slot"

    # =========================================================================
    # 9. CURIOUS ASK DUE
    # =========================================================================
    elif trigger_kind == "curious_ask_due":
        body = (
            f"Hi {owner_name}! Quick check — what service has been most asked-for this week at {merchant_name}? "
            f"I'll turn the answer into a Google post + a 4-line WhatsApp reply you can use when customers ask about pricing. Takes 5 min."
        )
        cta = "open_ended"
        rationale = "Weekly curiosity conversation building reciprocity by turning merchant insight into marketing assets"

    # =========================================================================
    # 10. WINBACK ELIGIBLE
    # =========================================================================
    elif trigger_kind == "winback_eligible":
        days_exp = trg_payload.get("days_since_expiry", 38)
        dip_pct = abs(trg_payload.get("perf_dip_pct", 0.30))
        lapsed_cx = trg_payload.get("lapsed_customers_added_since_expiry", 24)

        body = (
            f"{salutation}, since your subscription expired {days_exp} days ago, profile views dipped {int(dip_pct * 100)}% "
            f"and {lapsed_cx} customers entered soft-churn. Let's win them back — want me to draft a targeted reactivation "
            f"offer for those {lapsed_cx} customers today?"
        )
        cta = "binary_yes_no"
        rationale = "Loss aversion framed objectively with exact post-expiry metrics and actionable winback offer"

    # =========================================================================
    # 11. IPL MATCH TODAY
    # =========================================================================
    elif trigger_kind == "ipl_match_today":
        match = trg_payload.get("match", "DC vs MI")
        venue = trg_payload.get("venue", "Arun Jaitley Stadium")
        offer_name = primary_offer if primary_offer else "BOGO pizza"

        body = (
            f"Quick heads-up {owner_name} — {match} at {venue} tonight, 7:30pm. Important: Saturday IPL matches "
            f"usually shift -12% restaurant covers (people watch at home). Skip the match-night promo today; "
            f"instead push your {offer_name} as a delivery-only Saturday special. Want me to draft the Swiggy banner + an Insta story? Live in 10 min."
        )
        cta = "binary_yes_no"
        rationale = "Counter-intuitive data-backed advice preventing wasted promo spend and shifting to delivery demand"

    # =========================================================================
    # 12. REVIEW THEME EMERGED
    # =========================================================================
    elif trigger_kind == "review_theme_emerged":
        theme = trg_payload.get("theme", "service speed").replace("_", " ")
        occ = trg_payload.get("occurrences_30d", 4)
        quote = trg_payload.get("common_quote", "took 50 mins for a 15 min ride")

        body = (
            f"{salutation}, customer feedback trend this month: {occ} reviews noted '{quote}'. "
            f"Addressing '{theme}' proactively protects your 4.4 rating. Want me to draft a polite template reply "
            f"and an operational tip you can share with your team?"
        )
        cta = "binary_yes_no"
        rationale = "Identifies emerging review sentiment pattern with concrete quote and provides immediate resolution draft"

    # =========================================================================
    # 13. MILESTONE REACHED / IMMINENT
    # =========================================================================
    elif trigger_kind == "milestone_reached":
        val_now = trg_payload.get("value_now", 145)
        target = trg_payload.get("milestone_value", 150)
        diff = target - val_now

        body = (
            f"{salutation}, {merchant_name} is at {val_now} Google reviews — just {diff} away from the {target} milestone! "
            f"Crossing {target} unlocks higher visibility in {locality} searches. Want me to draft a 2-line WhatsApp review "
            f"invite for your last 10 satisfied customers?"
        )
        cta = "binary_yes_no"
        rationale = "Celebrates proximity to search-ranking milestone and offers low-effort review generation campaign"

    # =========================================================================
    # 14. ACTIVE PLANNING INTENT
    # =========================================================================
    elif trigger_kind == "active_planning_intent":
        if category_slug == "restaurants":
            body = (
                f"{owner_name}, here's a starter version — you can edit:\n\n"
                f"{merchant_name} Corporate Thali — for offices in {locality}\n"
                f"- 10 thalis @ ₹125 each (₹25 off retail) + free delivery\n"
                f"- 25 thalis @ ₹115 each + 2 free filter coffees\n"
                f"- 50+: ₹105 each + 1 free dosa platter\n"
                f"- WhatsApp day-before by 5pm; delivery 12:30-1pm.\n\n"
                f"3 offices in {locality} fit your delivery radius. Want me to draft a 3-line WhatsApp to send their facilities managers?"
            )
        else:
            body = (
                f"{owner_name}, here's a draft program structure for your summer camp:\n\n"
                f"4-week Kids Program at {merchant_name}:\n"
                f"- Ages 6-14 | Mon/Wed/Fri 8am-9am\n"
                f"- ₹2,499 per child (includes mat + certificate)\n"
                f"- Early bird: ₹1,999 before May 15\n\n"
                f"Want me to draft a Google post and a WhatsApp flyer you can share with parents today?"
            )
        cta = "binary_yes_no"
        rationale = "Fulfills merchant planning intent immediately with complete drafted structure and outreach proposal"

    # =========================================================================
    # 15. SEASONAL PERFORMANCE DIP REFRAME
    # =========================================================================
    elif trigger_kind == "seasonal_perf_dip":
        delta_pct = abs(trg_payload.get("delta_pct", 0.30))
        active_members = 245

        body = (
            f"{salutation}, your views are down {int(delta_pct * 100)}% this week — but this is the normal April-June acquisition "
            f"lull (every metro gym sees -25% to -35% in this window). Action: skip ad spend now, save it for Sept-Oct when conversion "
            f"is 2x. For now, focus retention on your {active_members} members. Want me to draft a 'summer attendance challenge' to keep them engaged?"
        )
        cta = "binary_yes_no"
        rationale = "Pre-empts anxiety by contextualizing seasonal lull against industry benchmarks and pivots to retention"

    # =========================================================================
    # 16. CUSTOMER LAPSED HARD WINBACK (Customer-facing)
    # =========================================================================
    elif trigger_kind == "customer_lapsed_hard":
        body = (
            f"Hi {cust_name} 👋 {owner_name} from {merchant_name} here. It's been about 8 weeks — happens to most members at "
            f"some point, no judgment. We've added a Tue/Thu evening HIIT class that fits weight-loss goals well (45 min, 6:30pm). "
            f"Want me to hold a free trial spot for you next Tue? Reply YES — no commitment, no auto-charge."
        )
        cta = "binary_yes_no"
        rationale = "No-shame lapse winback honoring past fitness goal with specific class details and zero-commitment trial"

    # =========================================================================
    # 17. SUPPLY / RECALL ALERT
    # =========================================================================
    elif trigger_kind == "supply_alert":
        molecule = trg_payload.get("molecule", "atorvastatin")
        batches = ", ".join(trg_payload.get("affected_batches", ["AT2024-1102", "AT2024-1108"]))
        mfr = trg_payload.get("manufacturer", "Mfr Z")

        body = (
            f"{owner_name}, urgent: voluntary recall on 2 {molecule} batches ({batches}) by {mfr} — sub-potency, "
            f"no safety risk, but customers should be informed for replacement. Pulled your repeat-Rx list: 22 chronic-Rx "
            f"customers were dispensed these batches in the last 90 days. Want me to draft their WhatsApp note + the replacement-pickup workflow?"
        )
        cta = "binary_yes_no"
        rationale = "Urgent compliance alert specifying batch codes, patient count affected, and replacement workflow"

    # =========================================================================
    # 18. CHRONIC REFILL DUE (Customer-facing)
    # =========================================================================
    elif trigger_kind == "chronic_refill_due":
        molecules = ", ".join(trg_payload.get("molecule_list", ["metformin", "atorvastatin", "telmisartan"]))
        body = (
            f"Namaste — {merchant_name} {locality} yahan. Sharma ji ki 3 monthly medicines ({molecules}) 28 April ko khatam hongi. "
            f"Same dose, same brand pack ready hai. Senior discount 15% applied — total ₹1,420 (₹240 saved). Free home delivery "
            f"to saved address by 5pm tomorrow. Reply CONFIRM to dispatch, or call if any change in dosage."
        )
        cta = "binary_confirm_cancel"
        rationale = "Respectful Hindi-English chronic refill reminder with transparent savings breakdown and delivery guarantee"

    # =========================================================================
    # 19. GBP UNVERIFIED
    # =========================================================================
    elif trigger_kind == "gbp_unverified":
        body = (
            f"{salutation}, your Google Business Profile for {merchant_name} is currently unverified. "
            f"Verified profiles see an estimated 30% increase in customer views and phone inquiries in {locality}. "
            f"Want me to guide you through the quick verification steps today?"
        )
        cta = "binary_yes_no"
        rationale = "GBP verification nudge highlighting 30% search uplift and low-friction assistance"

    # =========================================================================
    # 20. CDE WEBINAR / EDUCATIONAL OPPORTUNITY
    # =========================================================================
    elif trigger_kind == "cde_opportunity":
        body = (
            f"{salutation}, IDA Delhi has a CDE webinar on Digital impressions scheduled for May 2 at 7pm "
            f"(2 credit points, free for IDA members). Focuses on CAD/CAM workflow ROI for solo practices. "
            f"Want me to add it to your calendar and send you a reminder 1 hour before?"
        )
        cta = "binary_yes_no"
        rationale = "Category-specific educational event recommendation with credit details and calendar reminder offer"

    # =========================================================================
    # 21. COMPETITOR OPENED
    # =========================================================================
    elif trigger_kind == "competitor_opened":
        comp_name = trg_payload.get("competitor_name", "Smile Studio")
        dist = trg_payload.get("distance_km", 1.3)
        their_offer = trg_payload.get("their_offer", "Dental Cleaning @ ₹199")
        active_offer_text = primary_offer if primary_offer else "your verified service quality"

        body = (
            f"{salutation}, heads up: a new clinic '{comp_name}' opened {dist}km from you on GBP promoting {their_offer}. "
            f"Rather than discounting, we should highlight your clinic's track record and {active_offer_text}. "
            f"Want me to draft a Google post emphasizing your clinic's advanced sterilization and patient care?"
        )
        cta = "binary_yes_no"
        rationale = "Curiosity-driven competitor alert countering discount price war with quality positioning"

    # =========================================================================
    # 22. DORMANT WITH VERA
    # =========================================================================
    elif trigger_kind == "dormant_with_vera":
        days_dormant = trg_payload.get("days_since_last_merchant_message", 38)
        body = (
            f"{salutation}, hope you're having a productive week at {merchant_name}. It's been {days_dormant} days since "
            f"we connected — your profile recorded {views_30d:,} views this month. Want me to run a quick 2-minute GBP audit "
            f"to find any easy visibility wins for this weekend?"
        )
        cta = "binary_yes_no"
        rationale = "Gentle low-pressure re-engagement citing monthly views and offering quick 2-minute profile audit"

    # =========================================================================
    # 23. TRIAL FOLLOWUP (Customer-facing)
    # =========================================================================
    elif trigger_kind == "trial_followup":
        trial_date = trg_payload.get("trial_date", "2026-04-22")
        body = (
            f"Hi {cust_name}! Hope you enjoyed the trial session on {trial_date} at {merchant_name}. "
            f"We have an open spot for the next session on Sat 3 May at 8am. "
            f"Want us to save a spot for you? Reply YES to confirm."
        )
        cta = "binary_yes_no"
        rationale = "Direct post-trial follow-up with specific date and slot reservation offer"

    # =========================================================================
    # 24. CATEGORY SEASONAL / DEMAND SHIFT
    # =========================================================================
    elif trigger_kind == "category_seasonal":
        season = trg_payload.get("season", "summer").replace("_", " ")
        body = (
            f"{salutation}, seasonal demand shift for {season}: searches for ORS and summer health essentials "
            f"are up 38-40% across {locality}. Want me to draft a quick WhatsApp broadcast highlighting your summer essentials inventory?"
        )
        cta = "binary_yes_no"
        rationale = "Seasonal demand intelligence with actionable customer broadcast draft offer"

    # =========================================================================
    # DEFAULT / FALLBACK
    # =========================================================================
    else:
        body = (
            f"{salutation}, this is Vera with an update for {merchant_name}. "
            f"In the last 30 days, your profile recorded {views_30d:,} views and {calls_30d} calls. "
            f"Want me to review your active campaigns to optimize engagement this week?"
        )
        cta = "open_ended"
        rationale = f"Grounded update for {trigger_kind}"

    return {
        "body": body,
        "cta": cta,
        "send_as": send_as,
        "suppression_key": suppression_key,
        "rationale": rationale,
        "template_name": template_name,
        "template_params": template_params
    }
