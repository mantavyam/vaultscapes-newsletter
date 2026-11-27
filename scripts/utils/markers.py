"""Text markers shared by every AlphaSignal template.

Layout-specific landmarks (greetings, section headings, sponsor phrases) live
with their template in scripts/templates/<name>.py. Only what is common to all
layouts — or used outside the cleaner/parser — stays here.
"""

# Sender identity
SENDER_ADDRESS = "news@alphasignal.ai"

# Long-form article sends carry a kicker ending in this phrase — observed as
# "Sunday Deep Dive" and "Technical Deep Dive". Matched on the suffix so a new
# prefix ("Weekend Deep Dive", ...) needs no code change.
ARTICLE_KICKER_SUFFIX = "Deep Dive"
# Author card: byline in an article, junk in a digest.
AUTHOR_HEADING = "Today's Author"

# Tracking / redirect hosts. Click-tracking links are resolved to their final
# destination at pipeline time; the open-tracking pixel is dropped outright.
TRACKING_HOSTS = ("app.alphasignal.ai", "link.alphasignal.ai")
TRACKING_PIXEL_PATH = "/o"
TRACKING_CLICK_PATH = "/c"

# Signal / news stat vocabulary ("2,022 Likes", "23,314 Stars", "879 Downloads")
STAT_TYPES = ("Likes", "Stars", "Downloads")
