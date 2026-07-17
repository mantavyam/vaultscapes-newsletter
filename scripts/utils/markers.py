"""Single source of truth for every text marker the pipeline anchors on.

The AlphaSignal email HTML is ~70 nested tables with almost no CSS classes,
so cleaning and parsing are driven by these text landmarks. When AlphaSignal
changes their template, this file is the first (and usually only) place to fix.
"""

# Sender identity
SENDER_ADDRESS = "news@alphasignal.ai"

# Section headings (leading text of a top-level section table)
GREETING = "Hey,"
SUMMARY_HEADING = "Summary"
SIGNALS_HEADING = "Signals"
AUTHOR_HEADING = "Today's Author"
READ_TIME_PREFIX = "Read time:"

# News block categories all start with this prefix ("Top Repo", "Top News",
# "Top Tutorial", "Top Paper", ...). Matched by prefix so new categories
# survive without a code change.
NEWS_CATEGORY_PREFIX = "Top "

# Sponsor / advert landmarks
SPONSOR_PRESENTED_BY = "Presented by"
SPONSOR_PARTNERSHIP = "In Partnership with"
SPONSOR_PARTNER_LINK = "partner with us"

# Junk link rows between blocks
FORWARD_LINK = "forward"

# Footer landmarks (footer starts at the mission statement)
FOOTER_MISSION = "At Alpha Signal, our mission"
FOOTER_PROMOTE = "Looking to promote your company"
FOOTER_POLL = "How was today's email?"
FOOTER_UNSUBSCRIBE = "unsubscribe"

# Header nav links (the pre-greeting block)
HEADER_NAV = ("Signup", "Work With Us", "Follow on X", "Archive")

# Tracking / redirect hosts. Click-tracking links are resolved to their final
# destination at pipeline time; the open-tracking pixel is dropped outright.
TRACKING_HOSTS = ("app.alphasignal.ai", "link.alphasignal.ai")
TRACKING_PIXEL_PATH = "/o"
TRACKING_CLICK_PATH = "/c"

# Signal item stat vocabulary ("2,022 Likes", "23,314 Stars", "879 Downloads")
STAT_TYPES = ("Likes", "Stars", "Downloads")
