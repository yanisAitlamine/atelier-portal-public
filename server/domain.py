"""Portal-only rules. No payment, model, pipeline, builder or publication calls."""
import copy
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

CATALOG = {
    "extra_page": ("Additional standard page", 9900),
    "small_edit": ("Small content edit", None),
    "redesign": ("Design refresh", None),
    "advanced": ("Advanced feature", None),
}
PAGES = {"Home", "About", "Services", "Contact", "Gallery", "FAQ"}
STYLES = {"Warm & natural", "Clean & modern", "Bold & expressive"}


class PortalError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def uid():
    return str(uuid.uuid4())


def exact(obj, keys):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        raise PortalError("Invalid request fields.")


def text(value, minimum=3, maximum=3000):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise PortalError("Check the form fields and try again.")
    return value.strip()


def url(value):
    value = text(value, 0, 1000)
    if value:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise PortalError("Use an HTTP or HTTPS reference URL.")
    return value


def validate_brief(brief):
    exact(brief, ("businessName", "industry", "description", "audience", "pages", "style", "website"))
    result = {"businessName": text(brief["businessName"], 2, 160), "industry": text(brief["industry"], 2, 160),
              "description": text(brief["description"], 20, 4000), "audience": text(brief["audience"], 3, 300),
              "website": url(brief["website"])}
    if not isinstance(brief["pages"], list) or not 1 <= len(brief["pages"]) <= 6:
        raise PortalError("Choose between one and six pages.")
    if any(not isinstance(p, str) or p not in PAGES for p in brief["pages"]) or len(set(brief["pages"])) != len(brief["pages"]):
        raise PortalError("Choose distinct standard pages.")
    if not isinstance(brief["style"], str) or brief["style"] not in STYLES:
        raise PortalError("Choose a valid style.")
    result.update(pages=brief["pages"], style=brief["style"])
    return result


SAMPLE = {"businessName": "Studio Botanique", "industry": "Floral design studio",
          "description": "A seasonal floral studio creating thoughtful arrangements for everyday moments, intimate weddings and meaningful celebrations.",
          "audience": "People looking for seasonal flowers and thoughtful event floristry",
          "pages": ["Home", "About", "Services", "Contact"], "style": "Warm & natural", "website": ""}


def create_project(raw):
    sample = isinstance(raw, dict) and raw == {"sample": True}
    if not sample:
        exact(raw, ("brief",))
    brief = validate_brief(SAMPLE if sample else raw["brief"])
    at = now()
    project_id = uid()
    return {"id": project_id, "name": brief["businessName"], "revision": 1, "createdAt": at, "updatedAt": at,
            "sample": sample, "brief": brief, "subscription": "not_started", "status": "brief_ready",
            "preview": None, "requests": [],
            "messages": [{"id": uid(), "projectId": project_id, "kind": "initial_quote", "role": "assistant", "at": at, "text":
                "Welcome to your fictional sample website. Chat about your ideas and explore concept previews before payment. The creation quote is available here whenever you’re ready." if sample else
                f"Your brief for {brief['businessName']} is saved. Chat about your ideas before accepting a quote. The draft offer is €499 for creation and €39/month for hosting and maintenance after launch. Review the creation quote here whenever you’re ready."}],
            "activity": [{"id": uid(), "at": at, "text": "Sample project created" if sample else "Website brief saved"}],
            "initialQuote": {"status": "draft", "cents": 49900, "monthlyCents": 3900, "version": 1}}


def reply(message):
    if re.search(r"\b(price|cost|pricing|pay|payment)\b", message, re.I):
        return "The draft offer is €499 for creation and €39/month after launch. A standard additional page is €99; redesigns start at €149 with a custom quote. Payments are not connected, so this portal cannot charge you."
    if re.search(r"\b(shop|ecommerce|e-commerce|checkout|booking|inventory|login|database|integration)\b", message, re.I):
        return "That needs a scope review and custom quote. Select ‘Advanced feature’ in this chat when you want to submit it for review. No development starts automatically."
    if re.search(r"\b(publish|launch|deploy|live)\b", message, re.I):
        return "You can review a concept and record approval here. The production builder and customer website hosting are not connected. Approval does not publish a website."
    return "Your message is saved. This first version uses guided replies; AI and human support are not connected. You can keep discussing your ideas before payment. Select a service type in this chat when you want to submit a specific change for a draft quote or scope review. Image references can be shared by URL; uploads are not connected yet."


def transition(current, action):
    if not isinstance(action, dict) or not isinstance(action.get("type"), str):
        raise PortalError("Choose a valid action.")
    p = copy.deepcopy(current)
    kind = action["type"]

    def event(value):
        p["activity"].insert(0, {"id": uid(), "at": now(), "text": value})
        p["activity"] = p["activity"][:100]

    def message(role, value, **metadata):
        p["messages"].append({"id": uid(), "projectId": p["id"], "at": now(), "role": role, "text": value, **metadata})
        p["messages"] = p["messages"][-100:]

    def save_request(category, description, asset_url=""):
        category = text(category, 1, 30)
        if category not in CATALOG:
            raise PortalError("Choose a valid change category.")
        if sum(r["status"] != "cancelled" for r in p["requests"]) >= 20:
            raise PortalError("You have 20 open requests. Cancel one before adding another.", 409)
        title, cents = CATALOG[category]
        request_id = uid()
        p["requests"].insert(0, {"id": request_id, "category": category, "title": title, "description": description,
            "assetUrl": url(asset_url), "status": "quoted" if cents is not None else "needs_scope_review",
            "cents": cents, "at": now(), "quoteVersion": 1})
        event(f"{title} requested")
        message("assistant", "Change saved with a draft price of €99. Review the quote here in the chat. Acceptance does not collect payment." if cents is not None else
                "Change saved for scope and eligibility review. No free edit is authorized and no work starts automatically. The proposed subscription is not active.",
                kind="request", requestId=request_id)

    if kind == "message":
        exact(action, ("type", "text", "serviceCategory") if "serviceCategory" in action else ("type", "text"))
        value = text(action["text"])
        message("user", value)
        if "serviceCategory" in action:
            save_request(action["serviceCategory"], value)
        else:
            message("assistant", reply(value))
    elif kind == "accept_initial_quote":
        exact(action, ("type",))
        if p["initialQuote"]["status"] != "draft":
            raise PortalError("This quote was already accepted.", 409)
        p["initialQuote"]["status"] = "accepted_pending_payment"
        p["status"] = "awaiting_payment"
        event("Creation quote accepted · no payment collected")
        message("assistant", "Creation quote acceptance saved. No payment was collected, no subscription started and no production build was queued.", kind="status")
    elif kind == "request":
        exact(action, ("type", "category", "description", "assetUrl"))
        description = text(action["description"])
        message("user", description)
        save_request(action["category"], description, action["assetUrl"])
    elif kind in ("accept_request", "cancel_request"):
        exact(action, ("type", "requestId"))
        request_id = text(action["requestId"], 36, 36)
        r = next((r for r in p["requests"] if r["id"] == request_id), None)
        if not r:
            raise PortalError("Request not found.", 404)
        if kind == "accept_request":
            if r["status"] != "quoted" or r["cents"] is None:
                raise PortalError("No fixed-price quote is available for this request.", 409)
            r["status"] = "accepted_pending_payment"
            event(f"{r['title']}: quote accepted · payment pending")
            message("assistant", f"{r['title']}: quote acceptance saved. Payment is pending; no work starts automatically.", kind="status", requestId=request_id)
        else:
            if r["status"] == "cancelled":
                raise PortalError("Request already cancelled.", 409)
            r["status"] = "cancelled"
            event(f"{r['title']} cancelled")
            message("assistant", f"{r['title']}: change cancelled. No payment was collected by this portal.", kind="status", requestId=request_id)
    elif kind == "generate_preview":
        exact(action, ("type",))
        p["preview"] = {"version": (p["preview"] or {}).get("version", 0) + 1, "status": "awaiting_review",
                        "at": now(), "approvalAt": None, "feedback": ""}
        event(f"Concept preview v{p['preview']['version']} prepared")
        message("assistant", f"Concept preview v{p['preview']['version']} is ready for review. This is a template concept; no customer website has been built or published.", kind="status")
    elif kind in ("approve_preview", "preview_feedback"):
        exact(action, ("type", "previewVersion", "text") if kind == "preview_feedback" else ("type", "previewVersion"))
        preview = p["preview"]
        if not preview or preview["status"] != "awaiting_review" or type(action["previewVersion"]) is not int or action["previewVersion"] != preview["version"]:
            raise PortalError("Preview changed or already reviewed. Reload before approving.", 409)
        if kind == "approve_preview":
            preview.update(status="approved_pending_connection", approvalAt=now())
            event(f"Concept v{preview['version']} approved · publication not connected")
            message("assistant", f"Concept v{preview['version']} approval saved. Website publication is not connected.", kind="status")
        else:
            value = text(action["text"])
            preview.update(status="changes_requested", feedback=value)
            message("user", f"Concept v{preview['version']} feedback: {value}")
            event(f"Changes requested on concept v{preview['version']}")
            message("assistant", f"Your feedback on concept v{preview['version']} is saved. A new concept must be prepared for another review; feedback does not automatically rebuild the website.", kind="status")
    else:
        raise PortalError("Unknown action.")
    p["revision"] += 1
    p["updatedAt"] = now()
    return p
