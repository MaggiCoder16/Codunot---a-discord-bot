import discord
from discord import app_commands
from discord.ext import commands
import json, os, asyncio, re, random
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from typing import Literal, Optional
from dataclasses import dataclass, field
from encryption import save_encrypted, load_encrypted

MOD_DATA_FILE = "mod_data.json"

def load_mod_data() -> dict:
    default = {"guilds": {}, "warns": {}, "cases": {}, "notes": {}, "pending_unbans": {}}
    if not os.path.exists(MOD_DATA_FILE):
        return default
    try:
        raw = load_encrypted(MOD_DATA_FILE)
        data = json.loads(raw)
        for k, v in default.items():
            data.setdefault(k, v)
        return data
    except Exception as e:
        print(f"[MOD] Load error: {e}")
        return default

def save_mod_data(data: dict):
    try:
        save_encrypted(MOD_DATA_FILE, json.dumps(data, indent=2))
    except Exception as e:
        print(f"[MOD] Save error: {e}")

def _guild_cfg(data: dict, guild_id: int) -> dict:
    gid = str(guild_id)
    if gid not in data["guilds"]:
        data["guilds"][gid] = {
            "setup_complete": False,
            "automod_enabled": False,
            "bad_words": [],
            "automod_exempt_roles": [],
            "log_channels": [],
            "log_everywhere": False,
            "mod_roles": [],
            "links_allowed_server": True,
            "link_allowed_channels": [],
            "link_allowed_roles": [],
            "anti_spam": False,
            "spam_messages": 5,
            "spam_seconds": 5,
            "anti_raid": False,
            "raid_joins": 10,
            "raid_seconds": 10,
            "verification_enabled": False,
            "verification_mode": "button",
            "verification_channel_id": None,
            "verification_role_id": None,
            "verification_button_text": "✅ Verify",
            "verification_difficulty": "easy",
            "verification_branding": "",
            "shadowban_enabled": False,
            "shadowbanned_users": [],
            "sticky_messages": {},
            "adaptive_slowmode_enabled": False,
            "adaptive_threshold_messages": 50,
            "adaptive_threshold_seconds": 10,
            "adaptive_slowmode_seconds": 10,
            "adaptive_cooldown_seconds": 30,
        }
    return data["guilds"][gid]

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS + HELPERS
# ──────────────────────────────────────────────────────────────────────────────

COLOR_ORANGE  = 0xFFA500
COLOR_SUCCESS = 0x2ECC71
COLOR_DANGER  = 0xE74C3C
COLOR_INFO    = 0x5865F2
COLOR_GOLD    = 0xFFD700
COLOR_GREY    = 0x808080

setup_sessions: dict[str, dict] = {}
_spam_tracker: dict = defaultdict(lambda: defaultdict(lambda: deque(maxlen=25)))
_raid_tracker: dict = defaultdict(lambda: deque(maxlen=40))
_channel_msg_tracker: dict = defaultdict(lambda: deque(maxlen=300))


class VerifyButton(discord.ui.View):
    def __init__(self, cog: "ModerationCog", guild_id: int, user_id: int, button_text: str = "✅ Verify", timeout: int = 1800):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.verify_btn.label = button_text[:80] if button_text else "✅ Verify"

    @discord.ui.button(label="✅ Verify", style=discord.ButtonStyle.success)
    async def verify_btn(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This verification is not for you.", ephemeral=True)
            return
        ok, msg = await self.cog._grant_verification_role(interaction.guild, interaction.user)
        await interaction.response.send_message(msg, ephemeral=True)
        if ok:
            self.stop()


def _resolve_verification_channel(guild: discord.Guild, configured_channel_id: int | None) -> discord.TextChannel | None:
    if configured_channel_id:
        ch = guild.get_channel(int(configured_channel_id))
        if isinstance(ch, discord.TextChannel):
            return ch
    if isinstance(guild.system_channel, discord.TextChannel):
        return guild.system_channel
    for ch in guild.text_channels:
        return ch
    return None


async def _set_verification_visibility(
    guild: discord.Guild,
    verified_role: discord.Role,
    verification_channel_id: int | None,
    enabled: bool,
) -> tuple[int, int]:
    updated, failed = 0, 0
    for ch in guild.channels:
        if not isinstance(ch, discord.abc.GuildChannel):
            continue
        try:
            if enabled:
                if verification_channel_id and ch.id == int(verification_channel_id):
                    await ch.set_permissions(guild.default_role, view_channel=True, reason="Verification gate setup")
                    await ch.set_permissions(verified_role, view_channel=True, reason="Verification gate setup")
                else:
                    await ch.set_permissions(guild.default_role, view_channel=False, reason="Verification gate setup")
                    await ch.set_permissions(verified_role, view_channel=True, reason="Verification gate setup")
            else:
                await ch.set_permissions(guild.default_role, view_channel=None, reason="Verification gate disabled")
                await ch.set_permissions(verified_role, view_channel=None, reason="Verification gate disabled")
            updated += 1
        except Exception:
            failed += 1
    return updated, failed

def _parse_duration(s: str) -> Optional[timedelta]:
    m = re.match(r"^(\d+)([mhd])$", s.strip().lower())
    if not m:
        return None
    v, u = int(m.group(1)), m.group(2)
    return {"m": timedelta(minutes=v), "h": timedelta(hours=v), "d": timedelta(days=v)}.get(u)

def _progress_bar(step: int, total: int = 6) -> str:
    return "█" * step + "░" * (total - step)


@dataclass
class ParsedModIntent:
    action: str
    target_member: Optional[discord.Member] = None
    target_user_id: Optional[int] = None
    target_user_ids: list[int] = field(default_factory=list)
    target_channel: Optional[discord.TextChannel] = None
    minutes: Optional[int] = None
    duration_text: Optional[str] = None
    amount: Optional[int] = None
    case_number: Optional[int] = None
    note_action: Optional[str] = None
    note_text: Optional[str] = None
    reason: str = "No reason provided"
    missing_scopes: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# PERMISSIONS CHECKER
# ──────────────────────────────────────────────────────────────────────────────

def _check_bot_permissions(guild: discord.Guild) -> tuple[list[str], list[str]]:
    """
    Returns (have, missing) permission name lists.
    Checks all permissions needed for full mod functionality.
    """
    me = guild.me
    p  = me.guild_permissions

    required = {
        "Ban Members":       p.ban_members,
        "Kick Members":      p.kick_members,
        "Moderate Members":  p.moderate_members,
        "Manage Messages":   p.manage_messages,
        "Manage Channels":   p.manage_channels,
        "View Audit Log":    p.view_audit_log,
    }

    have    = [name for name, ok in required.items() if ok]
    missing = [name for name, ok in required.items() if not ok]
    return have, missing

def _perms_embed(guild: discord.Guild) -> discord.Embed | None:
    """
    Returns a warning embed if the bot is missing permissions, or None if all good.
    """
    _, missing = _check_bot_permissions(guild)
    if not missing:
        return None

    embed = discord.Embed(
        title="⚠️ Missing Permissions — Mod Features Will Be Limited",
        description=(
            "Codunot is missing some permissions in this server.\n"
            "**Mod commands that require these permissions will show `❌ No permission` errors.**\n\n"
            "To fix this, go to **Server Settings → Roles → Codunot** and enable the missing permissions below."
        ),
        color=COLOR_ORANGE,
    )
    embed.add_field(
        name="❌ Missing",
        value="\n".join(f"• `{p}`" for p in missing),
        inline=True,
    )
    embed.add_field(
        name="✅ Already Granted",
        value="\n".join(f"• `{p}`" for p in _check_bot_permissions(guild)[0]) or "None",
        inline=True,
    )
    embed.add_field(
        name="🔧 How to Fix",
        value=(
            "1. Open **Server Settings**\n"
            "2. Go to **Roles**\n"
            "3. Find and click the **Codunot** role\n"
            "4. Enable the missing permissions above\n"
            "5. Save changes — done! ✅"
        ),
        inline=False,
    )
    embed.set_footer(text="You can still run /setup-moderation — just fix perms when you can.")
    return embed

# ──────────────────────────────────────────────────────────────────────────────
# EMBED BUILDERS  (one per wizard step)
# ──────────────────────────────────────────────────────────────────────────────

def _wizard_embed(step: int, title: str, description: str, color=COLOR_ORANGE, total_steps: int = 7) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color,
                      timestamp=datetime.now(timezone.utc))
    e.set_footer(text=f"Moderation Setup  •  Step {step}/{total_steps}  [{_progress_bar(step, total=total_steps)}]")
    return e

def emb_step1() -> discord.Embed:
    return _wizard_embed(1, "🛡️ Step 1 — AutoMod",
        "**AutoMod** watches every message 24/7 — no moderator needs to be online.\n\n"
        "**What it handles automatically:**\n"
        "🤬  Deletes messages containing your blocked words\n"
        "🎭  Lets you exempt specific roles from AutoMod message checks\n"
        "🚫  Timeouts spammers *(threshold set in Step 5)*\n"
        "🚨  Locks the server if a raid is detected *(threshold set in Step 5)*\n\n"
        "If you click **Yes**, you'll fill in your bad word list next.\n\n"
        "❓ **Do you want to enable AutoMod?**"
    )

def emb_step2() -> discord.Embed:
    return _wizard_embed(2, "📋 Step 2 — Mod Log Channel",
        "Every mod action *(ban, kick, warn, auto-timeout, etc.)* is logged in detail.\n\n"
        "**Your options:**\n"
        "📌  **Specific channel(s)** — Pick one or more; all logs go there\n"
        "🌐  **Log Everywhere** — Log appears in the same channel as the action\n"
        "⏭️  **Skip** — No logging *(not recommended)*\n\n"
        "Select channel(s) from the dropdown, then hit **✅ Confirm Channels**.\n"
        "Or use the quick buttons below."
    )

def emb_step3() -> discord.Embed:
    return _wizard_embed(3, "🎖️ Step 3 — Mod Roles",
        "**Who can use moderation commands?**\n\n"
        "The **server owner** and anyone with **Ban / Kick / Timeout** permissions always have access.\n\n"
        "You can **also grant** specific roles access — great for Moderator or Helper roles "
        "that don't have those base Discord permissions.\n\n"
        "Select roles below, then click **✅ Confirm Roles**.\n"
        "Or click **⏭️ Skip** to use default Discord permissions only."
    )

def emb_step4() -> discord.Embed:
    return _wizard_embed(4, "🔗 Step 4 — Link Policy",
        "**Should members be allowed to post links?**\n\n"
        "✅  **Yes** — Links are allowed everywhere *(you pick nothing extra)*\n"
        "🚫  **No** — Links are **blocked server-wide**. You'll then choose:\n"
        "　　→ Which channels links **are** allowed in\n"
        "　　→ Which roles can bypass the block"
    )

def emb_step4b() -> discord.Embed:
    return _wizard_embed(4, "🔗 Step 4b — Allowed Channels",
        "Links are **blocked server-wide** by default.\n\n"
        "**Select channels where links ARE allowed:**\n"
        "*(e.g. #links, #resources, #bots, #media)*\n\n"
        "Leave empty and click **Continue →** to block links in every channel."
    )

def emb_step4c() -> discord.Embed:
    return _wizard_embed(4, "🔗 Step 4c — Bypass Roles",
        "**Select roles that can post links anywhere** *(bypass the server-wide block)*:\n"
        "*(e.g. Admins, Moderators, VIP)*\n\n"
        "Leave empty and click **Continue →** if no roles should bypass."
    )

def emb_step5() -> discord.Embed:
    return _wizard_embed(5, "⚡ Step 5 — AntiSpam & AntiRaid",
        "**AntiSpam 🚫**\n"
        "Auto-timeout members who send too many messages too fast.\n"
        "Default: **5 messages in 5 seconds** → 5-minute timeout\n\n"
        "**AntiRaid 🚨**\n"
        "Auto-lock all channels if too many members join at once.\n"
        "Default: **10 joins in 10 seconds** → full lockdown\n\n"
        "Click **Yes** to enable both with custom thresholds, or use the partial options."
    )

def emb_step6() -> discord.Embed:
    return _wizard_embed(6, "🧩 Step 6 — Premium/Enterprise Features",
        "Configure extra moderation features:\n\n"
        "1) **Button/Math Verification** (Premium+; Gold custom difficulty/text; Enterprise branding)\n"
        "2) **Shadowban** (Premium: 5, Gold: 20, Enterprise: unlimited)\n"
        "3) **Sticky Messages** (Premium: 1, Gold: 5, Enterprise: unlimited)\n"
        "4) **Adaptive Slowmode** (Gold+; Enterprise fully custom thresholds)\n\n"
        "You can skip this and configure later using slash commands."
    )

def emb_summary(s: dict) -> discord.Embed:
    e = discord.Embed(
        title="🛡️ Step 7 — Review & Confirm",
        description=(
            "Everything you configured is shown below.\n"
            "Click **✅ Confirm & Save** to activate moderation, "
            "or **🔄 Start Over** to go back to Step 1."
        ),
        color=COLOR_INFO,
        timestamp=datetime.now(timezone.utc),
    )

    e.add_field(
        name="🤖 AutoMod",
        value=f"✅ Enabled — {len(s.get('bad_words',[]))} blocked word(s)" if s.get("automod") else "⛔ Disabled",
        inline=True,
    )
    exempt_roles = s.get("automod_exempt_roles", [])
    e.add_field(
        name="🎭 AutoMod Exempt Roles",
        value=(" ".join(f"<@&{r}>" for r in exempt_roles) if exempt_roles else "None"),
        inline=True,
    )

    if s.get("log_everywhere"):
        log_val = "🌐 Log Everywhere"
    elif s.get("log_channels"):
        chs = " ".join(f"<#{c}>" for c in s["log_channels"][:3])
        extra = f" +{len(s['log_channels'])-3} more" if len(s["log_channels"]) > 3 else ""
        log_val = chs + extra
    else:
        log_val = "⛔ No logging"
    e.add_field(name="📋 Logging", value=log_val, inline=True)

    roles = s.get("mod_roles", [])
    e.add_field(
        name="🎖️ Mod Roles",
        value=(" ".join(f"<@&{r}>" for r in roles) if roles else "Default perms only"),
        inline=False,
    )

    if s.get("links_allowed_server"):
        link_val = "✅ Allowed everywhere"
    else:
        link_val = "🚫 Blocked server-wide"
        ach = s.get("link_allowed_channels", [])
        aro = s.get("link_allowed_roles", [])
        if ach: link_val += f"\n✅ Allowed in {len(ach)} channel(s)"
        if aro: link_val += f"\n✅ Bypass: {len(aro)} role(s)"
    e.add_field(name="🔗 Links", value=link_val, inline=True)

    spam_val = (f"✅ {s['spam_messages']} msgs / {s['spam_seconds']}s"
                if s.get("anti_spam") else "⛔ Off")
    raid_val = (f"✅ {s['raid_joins']} joins / {s['raid_seconds']}s"
                if s.get("anti_raid") else "⛔ Off")
    e.add_field(name="🚫 AntiSpam", value=spam_val, inline=True)
    e.add_field(name="🚨 AntiRaid", value=raid_val, inline=True)

    e.add_field(
        name="📋 Commands Unlocked After Save",
        value=(
            "`/warn` `/warns` `/clearwarns` `/case`\n"
            "`/ban` `/unban` `/modkick` `/mute` `/unmute`\n"
            "`/clear` `/slowmode` `/lock` `/unlock` `/userinfo`\n"
            "`/verification` `/shadowban` `/sticky` `/adaptive-slowmode`\n"
            "🌟 **Premium/Gold/Enterprise:** `/tempban` `/massban` `/modstats` `/note`"
        ),
        inline=False,
    )
    e.set_footer(text=f"Step 7/7  [{_progress_bar(7, total=7)}]  •  Moderation Setup")
    return e

# ──────────────────────────────────────────────────────────────────────────────
# MODALS
# ──────────────────────────────────────────────────────────────────────────────

class BadWordsModal(discord.ui.Modal, title="🤬 Set Bad Word List"):
    words = discord.ui.TextInput(
        label="Bad words (comma-separated)",
        style=discord.TextStyle.paragraph,
        placeholder="badword1, another bad phrase, word3, ...",
        required=True, max_length=2000,
    )
    def __init__(self, sk: str):
        super().__init__()
        self.sk = sk

    async def on_submit(self, interaction: discord.Interaction):
        session = setup_sessions.get(self.sk)
        if not session:
            await interaction.response.send_message("❌ Session expired.", ephemeral=True)
            return
        session["automod"] = True
        session["bad_words"] = [w.strip().lower() for w in self.words.value.split(",") if w.strip()]
        confirm = discord.Embed(
            title="✅ AutoMod Enabled",
            description=(
                f"**{len(session['bad_words'])} word(s)** added.\n"
                "Now pick any roles you want to exempt from AutoMod checks."
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.response.defer()
        msg = session["message"]
        await msg.edit(embed=confirm, view=None)
        await asyncio.sleep(1.5)
        await msg.edit(embed=emb_automod_exempt_roles(), view=AutoModExemptRolesView(self.sk))


def emb_automod_exempt_roles() -> discord.Embed:
    return _wizard_embed(1, "🛡️ Step 1b — AutoMod Exempt Roles",
        "Choose roles that should be **ignored by AutoMod message checks** (bad words, links, spam).\n\n"
        "Useful for announcement roles, bots, or trusted staff.\n"
        "Leave empty and continue if nobody should be exempt."
    )


class _ThresholdModalBase(discord.ui.Modal):
    """Shared base for spam/raid threshold modals."""
    def __init__(self, sk: str):
        super().__init__()
        self.sk = sk

    async def _save_and_advance(self, interaction: discord.Interaction):
        session = setup_sessions.get(self.sk)
        if not session:
            await interaction.response.send_message("❌ Session expired.", ephemeral=True)
            return
        await interaction.response.defer()
        await session["message"].edit(embed=emb_step6(), view=Step6View(self.sk))


class SpamRaidModal(_ThresholdModalBase, title="⚡ AntiSpam & AntiRaid Settings"):
    spam_msgs = discord.ui.TextInput(label="AntiSpam: max messages before timeout",  placeholder="5", default="5", max_length=3)
    spam_secs = discord.ui.TextInput(label="AntiSpam: time window (seconds)",        placeholder="5", default="5", max_length=3)
    raid_join = discord.ui.TextInput(label="AntiRaid: max joins before lockdown",    placeholder="10", default="10", max_length=3)
    raid_secs = discord.ui.TextInput(label="AntiRaid: time window (seconds)",        placeholder="10", default="10", max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        session = setup_sessions.get(self.sk)
        if not session:
            await interaction.response.send_message("❌ Session expired.", ephemeral=True)
            return
        try:
            session.update({
                "spam_messages": max(2, min(20,  int(self.spam_msgs.value))),
                "spam_seconds":  max(2, min(60,  int(self.spam_secs.value))),
                "raid_joins":    max(3, min(50,  int(self.raid_join.value))),
                "raid_seconds":  max(3, min(60,  int(self.raid_secs.value))),
                "anti_spam": True, "anti_raid": True,
            })
        except ValueError:
            session.update({"spam_messages":5,"spam_seconds":5,"raid_joins":10,"raid_seconds":10,
                            "anti_spam":True,"anti_raid":True})
        await self._save_and_advance(interaction)


class SpamOnlyModal(_ThresholdModalBase, title="🚫 AntiSpam Settings"):
    spam_msgs = discord.ui.TextInput(label="Max messages before timeout",  placeholder="5", default="5", max_length=3)
    spam_secs = discord.ui.TextInput(label="Time window (seconds)",        placeholder="5", default="5", max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        session = setup_sessions.get(self.sk)
        if not session: return
        try:
            session.update({"spam_messages": max(2, min(20, int(self.spam_msgs.value))),
                            "spam_seconds":  max(2, min(60, int(self.spam_secs.value))),
                            "anti_spam": True, "anti_raid": False})
        except ValueError:
            session.update({"spam_messages":5,"spam_seconds":5,"anti_spam":True,"anti_raid":False})
        await self._save_and_advance(interaction)


class RaidOnlyModal(_ThresholdModalBase, title="🚨 AntiRaid Settings"):
    raid_join = discord.ui.TextInput(label="Max joins before lockdown", placeholder="10", default="10", max_length=3)
    raid_secs = discord.ui.TextInput(label="Time window (seconds)",     placeholder="10", default="10", max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        session = setup_sessions.get(self.sk)
        if not session: return
        try:
            session.update({"raid_joins":   max(3, min(50, int(self.raid_join.value))),
                            "raid_seconds": max(3, min(60, int(self.raid_secs.value))),
                            "anti_spam": False, "anti_raid": True})
        except ValueError:
            session.update({"raid_joins":10,"raid_seconds":10,"anti_spam":False,"anti_raid":True})
        await self._save_and_advance(interaction)


class MassBanModal(discord.ui.Modal, title="🔨 Mass Ban Users"):
    user_ids = discord.ui.TextInput(
        label="User IDs (one per line or comma-separated)",
        style=discord.TextStyle.paragraph,
        placeholder="123456789012345678\n987654321098765432",
        required=True, max_length=2000,
    )
    reason = discord.ui.TextInput(label="Reason", default="Mass ban", max_length=500, required=False)

    def __init__(self, cog, guild: discord.Guild):
        super().__init__()
        self.cog   = cog
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason.value or "Mass ban"
        ids = [int(x) for x in re.split(r"[\s,]+", self.user_ids.value.strip()) if x.strip().isdigit()]
        if not ids:
            await interaction.response.send_message("❌ No valid user IDs found.", ephemeral=True)
            return
        await interaction.response.defer()
        success, failed = [], []
        for uid in ids[:10]:
            try:
                user = await self.cog.bot.fetch_user(uid)
                await self.guild.ban(user, reason=f"{interaction.user}: {reason}")
                success.append(str(user))
                self.cog._add_case(self.guild.id, "massban", uid, str(user),
                                   interaction.user.id, str(interaction.user), reason)
            except Exception:
                failed.append(str(uid))
        e = discord.Embed(title="🔨 Mass Ban Results",
                          color=COLOR_SUCCESS if success else COLOR_DANGER,
                          timestamp=datetime.now(timezone.utc))
        if success: e.add_field(name=f"✅ Banned ({len(success)})", value="\n".join(success), inline=False)
        if failed:  e.add_field(name=f"❌ Failed ({len(failed)})",  value="\n".join(failed),  inline=False)
        e.add_field(name="Reason", value=reason)
        await interaction.followup.send(embed=e)
        await self.cog._log_guild(self.guild, e)

# ──────────────────────────────────────────────────────────────────────────────
# SETUP WIZARD VIEWS
# ──────────────────────────────────────────────────────────────────────────────

class _WizardBase(discord.ui.View):
    """Base class for all setup wizard views — handles timeout + user guard."""

    def __init__(self, sk: str, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.sk = sk

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        session = setup_sessions.get(self.sk, {})
        if interaction.user.id != session.get("user_id"):
            await interaction.response.send_message(
                "❌ Only the person who started `/setup-moderation` can interact with this.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        session = setup_sessions.pop(self.sk, None)
        if session:
            msg = session.get("message")
            if msg:
                try:
                    await msg.edit(
                        embed=discord.Embed(
                            title="⏰ Setup Timed Out",
                            description="Run `/setup-moderation` to try again.",
                            color=COLOR_DANGER,
                        ),
                        view=None,
                    )
                except Exception:
                    pass


class Step1View(_WizardBase):
    @discord.ui.button(label="✅ Yes, enable AutoMod", style=discord.ButtonStyle.success, row=0)
    async def yes_btn(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(BadWordsModal(self.sk))

    @discord.ui.button(label="❌ No, skip AutoMod", style=discord.ButtonStyle.secondary, row=0)
    async def no_btn(self, interaction: discord.Interaction, _):
        s = setup_sessions[self.sk]
        s["automod"] = False
        s["bad_words"] = []
        s["automod_exempt_roles"] = []
        await interaction.response.edit_message(embed=emb_step2(), view=Step2View(self.sk))


class AutoModExemptRolesView(_WizardBase):
    def __init__(self, sk: str):
        super().__init__(sk)
        self._selected: list[int] = []

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Roles to exempt from AutoMod checks…",
        min_values=0, max_values=10,
        row=0,
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self._selected = [r.id for r in select.values]
        await interaction.response.defer()

    @discord.ui.button(label="Continue →", style=discord.ButtonStyle.primary, row=1)
    async def cont_btn(self, interaction: discord.Interaction, _):
        setup_sessions[self.sk]["automod_exempt_roles"] = self._selected
        await interaction.response.edit_message(embed=emb_step2(), view=Step2View(self.sk))


class Step2View(_WizardBase):
    def __init__(self, sk: str):
        super().__init__(sk)
        self._selected: list[int] = []

    @discord.ui.select(cls=discord.ui.ChannelSelect,
        placeholder="Pick log channel(s)…",
        min_values=0, max_values=10,
        channel_types=[discord.ChannelType.text],
        row=0,
    )
    async def ch_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self._selected = [c.id for c in select.values]
        await interaction.response.defer()

    @discord.ui.button(label="✅ Confirm Channels", style=discord.ButtonStyle.success, row=1)
    async def confirm_btn(self, interaction: discord.Interaction, _):
        if not self._selected:
            await interaction.response.send_message("❌ Select at least one channel first.", ephemeral=True)
            return
        s = setup_sessions[self.sk]
        s["log_channels"] = self._selected
        s["log_everywhere"] = False
        await interaction.response.edit_message(embed=emb_step3(), view=Step3View(self.sk))

    @discord.ui.button(label="🌐 Log Everywhere", style=discord.ButtonStyle.primary, row=1)
    async def everywhere_btn(self, interaction: discord.Interaction, _):
        s = setup_sessions[self.sk]
        s["log_channels"] = []
        s["log_everywhere"] = True
        await interaction.response.edit_message(embed=emb_step3(), view=Step3View(self.sk))

    @discord.ui.button(label="⏭️ Skip (No Logging)", style=discord.ButtonStyle.secondary, row=1)
    async def skip_btn(self, interaction: discord.Interaction, _):
        s = setup_sessions[self.sk]
        s["log_channels"] = []
        s["log_everywhere"] = False
        await interaction.response.edit_message(embed=emb_step3(), view=Step3View(self.sk))


class Step3View(_WizardBase):
    def __init__(self, sk: str):
        super().__init__(sk)
        self._selected: list[int] = []

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Pick mod role(s)…",
        min_values=0, max_values=10,
        row=0,
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self._selected = [r.id for r in select.values]
        await interaction.response.defer()

    @discord.ui.button(label="✅ Confirm Roles", style=discord.ButtonStyle.success, row=1)
    async def confirm_btn(self, interaction: discord.Interaction, _):
        if not self._selected:
            await interaction.response.send_message("❌ Select at least one role first.", ephemeral=True)
            return
        setup_sessions[self.sk]["mod_roles"] = self._selected
        await interaction.response.edit_message(embed=emb_step4(), view=Step4View(self.sk))

    @discord.ui.button(label="⏭️ Skip (Default Perms Only)", style=discord.ButtonStyle.secondary, row=1)
    async def skip_btn(self, interaction: discord.Interaction, _):
        setup_sessions[self.sk]["mod_roles"] = []
        await interaction.response.edit_message(embed=emb_step4(), view=Step4View(self.sk))


class Step4View(_WizardBase):
    @discord.ui.button(label="✅ Yes, allow links", style=discord.ButtonStyle.success, row=0)
    async def yes_btn(self, interaction: discord.Interaction, _):
        s = setup_sessions[self.sk]
        s.update({"links_allowed_server": True, "link_allowed_channels": [], "link_allowed_roles": []})
        await interaction.response.edit_message(embed=emb_step5(), view=Step5View(self.sk))

    @discord.ui.button(label="🚫 No, block links server-wide", style=discord.ButtonStyle.danger, row=0)
    async def no_btn(self, interaction: discord.Interaction, _):
        setup_sessions[self.sk]["links_allowed_server"] = False
        await interaction.response.edit_message(embed=emb_step4b(), view=Step4bView(self.sk))


class Step4bView(_WizardBase):
    def __init__(self, sk: str):
        super().__init__(sk)
        self._selected: list[int] = []

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Channels where links ARE allowed…",
        min_values=0, max_values=25,
        channel_types=[discord.ChannelType.text],
        row=0,
    )
    async def ch_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self._selected = [c.id for c in select.values]
        await interaction.response.defer()

    @discord.ui.button(label="Continue →", style=discord.ButtonStyle.primary, row=1)
    async def cont_btn(self, interaction: discord.Interaction, _):
        setup_sessions[self.sk]["link_allowed_channels"] = self._selected
        await interaction.response.edit_message(embed=emb_step4c(), view=Step4cView(self.sk))


class Step4cView(_WizardBase):
    def __init__(self, sk: str):
        super().__init__(sk)
        self._selected: list[int] = []

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Roles that can post links anywhere…",
        min_values=0, max_values=10,
        row=0,
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self._selected = [r.id for r in select.values]
        await interaction.response.defer()

    @discord.ui.button(label="Continue →", style=discord.ButtonStyle.primary, row=1)
    async def cont_btn(self, interaction: discord.Interaction, _):
        setup_sessions[self.sk]["link_allowed_roles"] = self._selected
        await interaction.response.edit_message(embed=emb_step5(), view=Step5View(self.sk))


class Step5View(_WizardBase):
    @discord.ui.button(label="✅ Both (AntiSpam + AntiRaid)", style=discord.ButtonStyle.success, row=0)
    async def both_btn(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(SpamRaidModal(self.sk))

    @discord.ui.button(label="🚫 AntiSpam Only", style=discord.ButtonStyle.primary, row=0)
    async def spam_btn(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(SpamOnlyModal(self.sk))

    @discord.ui.button(label="🚨 AntiRaid Only", style=discord.ButtonStyle.primary, row=0)
    async def raid_btn(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(RaidOnlyModal(self.sk))

    @discord.ui.button(label="❌ Skip Both", style=discord.ButtonStyle.secondary, row=1)
    async def skip_btn(self, interaction: discord.Interaction, _):
        s = setup_sessions[self.sk]
        s.update({"anti_spam": False, "anti_raid": False})
        await interaction.response.edit_message(embed=emb_step6(), view=Step6View(self.sk))


class Step6View(_WizardBase):
    @discord.ui.button(label="⏭️ Skip Extras", style=discord.ButtonStyle.secondary, row=0)
    async def skip_btn(self, interaction: discord.Interaction, _):
        s = setup_sessions[self.sk]
        await interaction.response.edit_message(embed=emb_summary(s), view=SummaryView(self.sk))


class SummaryView(_WizardBase):
    @discord.ui.button(label="✅ Confirm & Save", style=discord.ButtonStyle.success,
                       emoji="🛡️", row=0)
    async def confirm_btn(self, interaction: discord.Interaction, _):
        s = setup_sessions.pop(self.sk, None)
        if not s:
            await interaction.response.send_message("❌ Session expired.", ephemeral=True)
            return

        cog: ModerationCog = interaction.client.cogs.get("ModerationCog")
        if cog is None:
            await interaction.response.send_message("❌ Cog not found.", ephemeral=True)
            return

        cfg = _guild_cfg(cog.mod_data, interaction.guild.id)
        cfg.update({
            "setup_complete":       True,
            "automod_enabled":      s.get("automod", False),
            "bad_words":            s.get("bad_words", []),
            "automod_exempt_roles": s.get("automod_exempt_roles", []),
            "log_channels":         s.get("log_channels", []),
            "log_everywhere":       s.get("log_everywhere", False),
            "mod_roles":            s.get("mod_roles", []),
            "links_allowed_server": s.get("links_allowed_server", True),
            "link_allowed_channels":s.get("link_allowed_channels", []),
            "link_allowed_roles":   s.get("link_allowed_roles", []),
            "anti_spam":            s.get("anti_spam", False),
            "spam_messages":        s.get("spam_messages", 5),
            "spam_seconds":         s.get("spam_seconds", 5),
            "anti_raid":            s.get("anti_raid", False),
            "raid_joins":           s.get("raid_joins", 10),
            "raid_seconds":         s.get("raid_seconds", 10),
        })
        cog._save()

        done = discord.Embed(
            title="🛡️ Moderation is now ACTIVE!",
            description=(
                "Your server is protected. All mod commands are unlocked.\n\n"
                "**Quick reference:**\n"
                "`/warn` `/ban` `/mute` `/clear` `/lock` `/userinfo`\n"
                "`/verification` `/shadowban` `/sticky` `/adaptive-slowmode`\n"
                "`/case` — lookup any mod action by case number\n"
                "🌟 **Premium/Gold:** `/tempban` `/massban` `/modstats` `/note`\n\n"
                "Use `/setup-moderation` any time to reconfigure."
            ),
            color=COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc),
        )
        done.set_footer(text="Moderation Setup Complete")

        # Send done embed, then send perms warning as a follow-up if needed
        await interaction.response.edit_message(embed=done, view=None)
        perms_warn = _perms_embed(interaction.guild)
        if perms_warn:
            await interaction.followup.send(embed=perms_warn, ephemeral=True)

    @discord.ui.button(label="🔄 Start Over", style=discord.ButtonStyle.danger, row=0)
    async def restart_btn(self, interaction: discord.Interaction, _):
        msg = setup_sessions[self.sk].get("message")
        uid = setup_sessions[self.sk].get("user_id")
        gid = setup_sessions[self.sk].get("guild_id")
        setup_sessions[self.sk] = {
            "message": msg, "user_id": uid, "guild_id": gid,
            "automod": False, "bad_words": [],
            "automod_exempt_roles": [],
            "log_channels": [], "log_everywhere": False,
            "mod_roles": [],
            "links_allowed_server": True, "link_allowed_channels": [], "link_allowed_roles": [],
            "anti_spam": False, "spam_messages": 5, "spam_seconds": 5,
            "anti_raid": False, "raid_joins": 10, "raid_seconds": 10,
            "verification_enabled": False,
            "verification_mode": "button",
            "verification_channel_id": None,
            "verification_role_id": None,
            "verification_button_text": "✅ Verify",
            "verification_difficulty": "easy",
            "verification_branding": "",
            "shadowban_enabled": False,
            "shadowbanned_users": [],
            "sticky_messages": {},
            "adaptive_slowmode_enabled": False,
            "adaptive_threshold_messages": 50,
            "adaptive_threshold_seconds": 10,
            "adaptive_slowmode_seconds": 10,
            "adaptive_cooldown_seconds": 30,
        }
        await interaction.response.edit_message(embed=emb_step1(), view=Step1View(self.sk))

# ──────────────────────────────────────────────────────────────────────────────
# MAIN COG
# ──────────────────────────────────────────────────────────────────────────────

class ModerationCog(commands.Cog, name="ModerationCog"):
    ACTION_PATTERNS = {
        "mute": (
            "timeout", "time out", "mute", "silence", "quiet", "shut up", "jail",
            "put in timeout", "timeout for", "mute for",
        ),
        "unmute": (
            "unmute", "untimeout", "remove timeout", "remove time out",
            "release from timeout", "let them talk", "unsilence",
        ),
        "ban": (
            "ban", "banish", "blacklist", "remove permanently", "perm ban", "perma ban",
        ),
        "unban": (
            "unban", "pardon", "revoke ban", "lift ban", "remove ban",
        ),
        "kick": (
            "kick", "boot", "remove from server", "kick out", "throw out", "modkick",
        ),
        "warn": (
            "warn", "warning", "strike", "give a strike", "issue warning", "caution",
        ),
        "clear": ("clear", "purge", "delete messages", "wipe messages", "clean chat"),
        "clearwarns": ("clearwarns", "clear warns", "wipe warns", "reset warnings"),
        "case": ("case", "show case", "case number", "lookup case"),
        "lock": ("lock", "lockdown", "lock channel", "close channel"),
        "unlock": ("unlock", "unlock channel", "open channel", "remove lockdown"),
        "slowmode": ("slowmode", "slow mode", "set slowmode", "disable slowmode"),
        "tempban": ("tempban", "temp ban", "temporary ban"),
        "massban": ("massban", "mass ban", "bulk ban"),
        "userinfo": ("userinfo", "user info", "member info", "check user", "inspect user"),
        "note": ("note", "notes", "noteadd", "noteclear", "note view", "note add", "note clear"),
    }

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.mod_data = load_mod_data()

    async def cog_load(self):
        asyncio.create_task(self._process_pending_unbans())

    def _save(self):
        save_mod_data(self.mod_data)

    def _cfg(self, guild_id: int) -> dict:
        return _guild_cfg(self.mod_data, guild_id)

    def _is_setup(self, guild_id: int) -> bool:
        return self._cfg(guild_id).get("setup_complete", False)

    def _add_case(self, guild_id: int, ctype: str, user_id: int, user_str: str,
                  mod_id: int, mod_str: str, reason: str, extra: dict = None) -> int:
        gid = str(guild_id)
        self.mod_data.setdefault("cases", {}).setdefault(gid, {"next_case": 1, "by_number": {}})
        c = self.mod_data["cases"][gid]
        n = c["next_case"]
        c["by_number"][str(n)] = {
            "type": ctype, "user_id": user_id, "user": user_str,
            "moderator_id": mod_id, "moderator": mod_str, "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "extra": extra or {},
        }
        c["next_case"] = n + 1
        self._save()
        return n

    async def _log_guild(self, guild: discord.Guild, embed: discord.Embed,
                         action_channel_id: int = None):
        cfg = self._cfg(guild.id)
        if cfg.get("log_everywhere") and action_channel_id:
            ch = guild.get_channel(action_channel_id)
            if ch:
                try: await ch.send(embed=embed); return
                except Exception: pass
        for cid in cfg.get("log_channels", []):
            ch = guild.get_channel(int(cid))
            if ch:
                try: await ch.send(embed=embed)
                except Exception as e: print(f"[MOD LOG] {e}")

    def _has_base_perms(self, member: discord.Member) -> bool:
        p = member.guild_permissions
        return p.administrator or p.ban_members or p.kick_members or p.moderate_members

    async def _gate(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("❌ Server only.", ephemeral=True)
            return False
        if not self._is_setup(interaction.guild.id):
            embed = discord.Embed(
                title="⚠️ Moderation Not Configured",
                description=(
                    "This server hasn't set up moderation yet.\n\n"
                    "The **server owner** or a member with **Ban / Kick / Timeout** permissions "
                    "must run `/setup-moderation` first."
                ),
                color=COLOR_DANGER,
            )
            embed.add_field(name="Who can run it?",
                            value="Server owner, or anyone with Ban Members / Kick Members / Moderate Members permissions")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return await self._check_perms(interaction)

    async def _check_perms(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("❌ Server only.", ephemeral=True)
            return False
        if interaction.guild.owner_id == member.id or self._has_base_perms(member):
            return True
        mod_roles = self._cfg(interaction.guild.id).get("mod_roles", [])
        if any(r.id in mod_roles for r in member.roles):
            return True
        embed = discord.Embed(
            title="❌ No Mod Permission",
            description=(
                "You need one of:\\n"
                "• **Ban Members** permission\\n"
                "• **Kick Members** permission\\n"
                "• **Moderate Members** (Timeout) permission\\n"
                "• A configured **Mod Role**\\n\\n"
                "Ask a server admin if you believe this is wrong."
            ),
            color=COLOR_DANGER,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False


    def _member_can_mod_by_role(self, member: discord.Member) -> bool:
        if member.guild.owner_id == member.id or self._has_base_perms(member):
            return True
        mod_roles = self._cfg(member.guild.id).get("mod_roles", [])
        return any(r.id in mod_roles for r in member.roles)

    def _normalize_nlp_text(self, text: str) -> str:
        low = text.lower()
        low = re.sub(r"[^a-z0-9@#:_\-\s]", " ", low)
        low = re.sub(r"\s+", " ", low).strip()
        return low

    def _tokenize_nlp(self, text: str) -> list[str]:
        tokens = [t for t in text.split(" ") if t]
        normalized: list[str] = []
        for t in tokens:
            if len(t) > 5 and t.endswith("ing") and len(t[:-3]) >= 4:
                t = t[:-3]
            elif len(t) > 4 and t.endswith("ed") and len(t[:-2]) >= 4:
                t = t[:-2]
            elif len(t) > 4 and t.endswith("es") and len(t[:-2]) >= 4:
                t = t[:-2]
            elif len(t) > 3 and t.endswith("s") and len(t[:-1]) >= 4:
                t = t[:-1]
            normalized.append(t)
        return normalized

    def _extract_reason(self, text: str) -> str:
        m = re.search(
            r"(?:for\s+reason\s*(?:being)?|reason\s*[:=-]?|because|for)\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        if not m:
            return "No reason provided"
        reason = m.group(1).strip(" .,")
        reason = re.sub(r"^(?:\d+\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\b)\s*", "", reason, flags=re.IGNORECASE)
        reason = re.sub(r"^for\s+", "", reason, flags=re.IGNORECASE).strip()
        return reason[:500] if reason else "No reason provided"

    def _extract_minutes(self, text: str) -> Optional[int]:
        patterns = [
            r"(?:for\s+)?(\d{1,5})\s*(?:m|min|mins|minute|minutes)\b",
            r"(?:for\s+)?(\d{1,4})\s*(?:h|hr|hrs|hour|hours)\b",
            r"(?:for\s+)?(\d{1,3})\s*(?:d|day|days)\b",
        ]
        m = re.search(patterns[0], text, re.IGNORECASE)
        if m:
            return max(1, min(40320, int(m.group(1))))
        m = re.search(patterns[1], text, re.IGNORECASE)
        if m:
            return max(1, min(40320, int(m.group(1)) * 60))
        m = re.search(patterns[2], text, re.IGNORECASE)
        if m:
            return max(1, min(40320, int(m.group(1)) * 1440))
        return None

    def _extract_seconds(self, text: str) -> Optional[int]:
        m = re.search(r"(\d{1,5})\s*(?:s|sec|secs|second|seconds)\b", text, re.IGNORECASE)
        if m:
            return max(0, min(21600, int(m.group(1))))
        m = re.search(r"(\d{1,4})\s*(?:m|min|mins|minute|minutes)\b", text, re.IGNORECASE)
        if m:
            return max(0, min(21600, int(m.group(1)) * 60))
        return None

    def _extract_count(self, text: str, max_value: int) -> Optional[int]:
        m = re.search(r"\b(\d{1,4})\b", text)
        if not m:
            return None
        return max(1, min(max_value, int(m.group(1))))

    def _detect_action(self, text: str) -> Optional[str]:
        low = self._normalize_nlp_text(text)
        tokens = self._tokenize_nlp(low)
        token_set = set(tokens)

        scored: list[tuple[int, int, str]] = []
        priority = {
            "unban": 20, "unmute": 19, "clearwarns": 18, "unlock": 17,
            "tempban": 16, "massban": 15, "slowmode": 14, "note": 13,
            "case": 12, "userinfo": 11, "clear": 10, "lock": 9,
            "ban": 8, "mute": 7, "kick": 6, "warn": 5,
        }

        for action, variants in self.ACTION_PATTERNS.items():
            score = 0
            has_direct_phrase_match = False
            for phrase in variants:
                p = phrase.lower().strip()
                if re.search(rf"\b{re.escape(p)}\b", low):
                    has_direct_phrase_match = True
                    score += 8 + min(len(p), 12)
                    continue
                p_tokens = self._tokenize_nlp(self._normalize_nlp_text(p))
                if p_tokens and all(pt in token_set for pt in p_tokens):
                    score += 4 + len(p_tokens)
            if score and (has_direct_phrase_match or score >= 8):
                scored.append((score, priority.get(action, 0), action))

        if not scored:
            return None
        scored.sort(reverse=True)
        return scored[0][2]

    def _detect_note_action(self, text: str) -> str:
        low = text.lower()
        if any(k in low for k in ("note clear", "noteclear", "clear note", "clear notes")):
            return "clear"
        if any(k in low for k in ("note view", "view note", "show notes", "notes for")):
            return "view"
        return "add"

    async def _parse_nl_mod_intent(self, message: discord.Message) -> Optional[ParsedModIntent]:
        if not self.bot.user or self.bot.user not in message.mentions:
            return None

        text = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()
        if not text:
            return None

        action = self._detect_action(text)
        if not action:
            return None

        target_member = next((m for m in message.mentions if m.id != self.bot.user.id and m.id != message.author.id), None)
        target_user_id: Optional[int] = None
        target_user_ids = [int(x) for x in re.findall(r"\b(\d{15,22})\b", text)]
        if target_member and target_member.id not in target_user_ids:
            target_user_ids.append(target_member.id)

        channel_match = re.search(r"<#(\d+)>", message.content)
        target_channel = None
        if channel_match and message.guild:
            target_channel = message.guild.get_channel(int(channel_match.group(1)))
            if target_channel and not isinstance(target_channel, discord.TextChannel):
                target_channel = None

        minutes = self._extract_minutes(text)
        duration_match = re.search(r"\b\d+\s*[mhd]\b", text, re.IGNORECASE)
        duration_text = duration_match.group(0).replace(" ", "") if duration_match else None
        amount = self._extract_count(text, 100)
        case_match = re.search(r"(?:case\s*#?|#)(\d+)", text, re.IGNORECASE)
        case_number = int(case_match.group(1)) if case_match else None
        note_action = self._detect_note_action(text) if action == "note" else None
        note_text = None
        if action == "note" and note_action == "add":
            m = re.search(r"(?:note\s+add|noteadd|add\s+note)\s+.+?\s+(?:that|:)?\s*(.+)$", text, re.IGNORECASE)
            if m:
                note_text = m.group(1).strip()

        missing_scopes: list[str] = []
        if action in {"mute", "ban", "kick", "warn", "unmute", "clearwarns", "tempban", "userinfo", "note"} and not target_member:
            missing_scopes.append("user")
        if action == "unban" and not target_user_ids:
            missing_scopes.append("user_id")
        if action == "mute" and minutes is None:
            missing_scopes.append("minutes")
        if action == "clear" and amount is None:
            missing_scopes.append("amount")
        if action == "slowmode" and self._extract_seconds(text) is None and "disable" not in text.lower() and "off" not in text.lower():
            missing_scopes.append("seconds")
        if action == "case" and case_number is None:
            missing_scopes.append("case_number")
        if action == "tempban" and not duration_text:
            missing_scopes.append("duration")
        if action == "massban" and not target_user_ids:
            missing_scopes.append("user_ids")
        if action == "note" and note_action == "add" and not note_text:
            missing_scopes.append("note_text")

        if action == "unban" and target_user_ids:
            target_user_id = target_user_ids[0]

        return ParsedModIntent(
            action=action,
            target_member=target_member,
            target_user_id=target_user_id,
            target_user_ids=target_user_ids,
            target_channel=target_channel,
            minutes=minutes,
            duration_text=duration_text,
            amount=amount,
            case_number=case_number,
            note_action=note_action,
            note_text=note_text,
            reason=self._extract_reason(text),
            missing_scopes=missing_scopes,
        )

    async def _handle_nl_mod(self, message: discord.Message) -> bool:
        if not message.guild or not isinstance(message.author, discord.Member):
            return False

        parsed = await self._parse_nl_mod_intent(message)
        if not parsed:
            return False

        actor = message.author
        channel = message.channel

        if not self._is_setup(message.guild.id):
            await channel.send(
                "❌ This server hasn't set up moderation yet. Ask an admin to run `/setup-moderation` first.",
                delete_after=8,
            )
            return True

        if not self._member_can_mod_by_role(message.author):
            await channel.send("❌ You don't have permission to use moderation commands.", delete_after=8)
            return True

        if parsed.missing_scopes:
            scope_help = {
                "user": "mention a target user (`@user`)",
                "user_id": "provide the user ID",
                "minutes": "provide timeout minutes (e.g. `5m` or `10 minutes`)",
                "amount": "provide message count (1-100)",
                "seconds": "provide slowmode seconds (e.g. `10s`)",
                "case_number": "provide the case number (e.g. `case #12`)",
                "duration": "provide tempban duration (e.g. `30m`, `6h`, `2d`)",
                "user_ids": "provide one or more user IDs",
                "note_text": "provide note text",
            }
            action_examples = {
                "mute": "@Codunot timeout @user 5m for spam",
                "ban": "@Codunot ban @user for raiding",
                "kick": "@Codunot kick @user for trolling",
                "warn": "@Codunot warn @user for spam",
                "unmute": "@Codunot unmute @user",
                "clearwarns": "@Codunot clearwarns @user",
                "tempban": "@Codunot tempban @user 2d for repeated abuse",
                "userinfo": "@Codunot userinfo @user",
                "note": "@Codunot note add @user: repeated spam",
                "unban": "@Codunot unban 123456789012345678",
                "clear": "@Codunot clear 20",
                "slowmode": "@Codunot slowmode 10s",
                "case": "@Codunot case #12",
                "massban": "@Codunot massban 123456789012345678 234567890123456789",
            }
            missing = "\n".join(f"• {scope_help.get(s, s)}" for s in parsed.missing_scopes)
            example = action_examples.get(parsed.action, "@Codunot timeout @user 5m for spam")
            await channel.send(
                "❌ Missing required info for that moderation action. Please include:\n"
                f"{missing}\n\n"
                f"Example: `{example}`"
            )
            return True

        user = parsed.target_member
        reason = parsed.reason

        try:
            if parsed.action == "mute":
                if user.top_role >= actor.top_role and message.guild.owner_id != actor.id:
                    await channel.send("❌ Can't timeout someone with equal or higher role.", delete_after=8)
                    return True
                dur = parsed.minutes or 10
                await user.timeout(timedelta(minutes=dur), reason=reason)
                case_n = self._add_case(message.guild.id, "mute", user.id, str(user), actor.id, str(actor), reason, {"minutes": dur})
                e = discord.Embed(title="🔇 Member Muted", color=0xFF8C00, timestamp=datetime.now(timezone.utc))
                e.add_field(name="User", value=f"{user.mention} (`{user.id}`)")
                e.add_field(name="Duration", value=f"{dur} minutes")
                e.add_field(name="Reason", value=reason)
                e.add_field(name="Case #", value=f"#{case_n}")
                e.add_field(name="Moderator", value=actor.mention)
                await channel.send(embed=e)
                await self._log_guild(message.guild, e, channel.id)
                return True

            if parsed.action == "unmute":
                await user.timeout(None, reason=reason)
                e = discord.Embed(title="🔊 Member Unmuted", color=COLOR_SUCCESS, timestamp=datetime.now(timezone.utc))
                e.add_field(name="User", value=f"{user.mention} (`{user.id}`)")
                e.add_field(name="Moderator", value=actor.mention)
                await channel.send(embed=e)
                await self._log_guild(message.guild, e, channel.id)
                return True

            if parsed.action == "warn":
                gid, uid = str(message.guild.id), str(user.id)
                self.mod_data.setdefault("warns", {}).setdefault(gid, {}).setdefault(uid, [])
                self.mod_data["warns"][gid][uid].append({
                    "reason": reason, "moderator": str(actor), "moderator_id": actor.id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                count = len(self.mod_data["warns"][gid][uid])
                case_n = self._add_case(message.guild.id, "warn", user.id, str(user), actor.id, str(actor), reason)
                self._save()
                e = discord.Embed(title="⚠️ Member Warned", color=COLOR_GOLD, timestamp=datetime.now(timezone.utc))
                e.add_field(name="User", value=f"{user.mention} (`{user.id}`)")
                e.add_field(name="Reason", value=reason)
                e.add_field(name="Warn #", value=count)
                e.add_field(name="Case #", value=f"#{case_n}")
                e.add_field(name="Moderator", value=actor.mention)
                await channel.send(embed=e)
                await self._log_guild(message.guild, e, channel.id)
                return True

            if parsed.action == "clearwarns":
                gid, uid = str(message.guild.id), str(user.id)
                self.mod_data.setdefault("warns", {}).setdefault(gid, {})[uid] = []
                self._save()
                await channel.send(f"✅ All warnings cleared for {user.mention}.")
                return True

            if parsed.action == "kick":
                if user.top_role >= actor.top_role and message.guild.owner_id != actor.id:
                    await channel.send("❌ Can't kick someone with equal or higher role.", delete_after=8)
                    return True
                await user.kick(reason=f"{actor}: {reason}")
                case_n = self._add_case(message.guild.id, "kick", user.id, str(user), actor.id, str(actor), reason)
                e = discord.Embed(title="👢 Member Kicked", color=0xFF4500, timestamp=datetime.now(timezone.utc))
                e.add_field(name="User", value=f"{user} (`{user.id}`)")
                e.add_field(name="Reason", value=reason)
                e.add_field(name="Case #", value=f"#{case_n}")
                e.add_field(name="Moderator", value=actor.mention)
                await channel.send(embed=e)
                await self._log_guild(message.guild, e, channel.id)
                return True

            if parsed.action == "ban":
                if user.top_role >= actor.top_role and message.guild.owner_id != actor.id:
                    await channel.send("❌ Can't ban someone with equal or higher role.", delete_after=8)
                    return True
                await user.ban(reason=f"{actor}: {reason}", delete_message_days=0)
                case_n = self._add_case(message.guild.id, "ban", user.id, str(user), actor.id, str(actor), reason)
                e = discord.Embed(title="🔨 Member Banned", color=COLOR_DANGER, timestamp=datetime.now(timezone.utc))
                e.add_field(name="User", value=f"{user} (`{user.id}`)")
                e.add_field(name="Reason", value=reason)
                e.add_field(name="Case #", value=f"#{case_n}")
                e.add_field(name="Moderator", value=actor.mention)
                await channel.send(embed=e)
                await self._log_guild(message.guild, e, channel.id)
                return True

            if parsed.action == "tempban":
                td = _parse_duration((parsed.duration_text or "").lower())
                if not td:
                    await channel.send("❌ Invalid duration. Use like `30m`, `6h`, or `2d`.")
                    return True
                unban_at = (datetime.now(timezone.utc) + td).isoformat()
                await user.ban(reason=f"{actor}: [TEMPBAN {parsed.duration_text}] {reason}")
                gid_str = str(message.guild.id)
                self.mod_data.setdefault("pending_unbans", {}).setdefault(gid_str, []).append({"user_id": user.id, "unban_at": unban_at})
                case_n = self._add_case(message.guild.id, "tempban", user.id, str(user), actor.id, str(actor), reason, {"duration": parsed.duration_text, "unban_at": unban_at})
                self._save()
                asyncio.create_task(self._schedule_unban(message.guild.id, user.id, td.total_seconds()))
                e = discord.Embed(title="⏱️ Member Temp-Banned", color=COLOR_DANGER, timestamp=datetime.now(timezone.utc))
                e.add_field(name="User", value=f"{user} (`{user.id}`)")
                e.add_field(name="Duration", value=parsed.duration_text)
                e.add_field(name="Reason", value=reason)
                e.add_field(name="Case #", value=f"#{case_n}")
                await channel.send(embed=e)
                await self._log_guild(message.guild, e, channel.id)
                return True

            if parsed.action == "unban" and parsed.target_user_id:
                target_user = await self.bot.fetch_user(parsed.target_user_id)
                await message.guild.unban(target_user, reason=reason)
                e = discord.Embed(title="🔓 Member Unbanned", color=COLOR_SUCCESS, timestamp=datetime.now(timezone.utc))
                e.add_field(name="User", value=f"{target_user} (`{target_user.id}`)")
                e.add_field(name="Reason", value=reason)
                e.add_field(name="Moderator", value=actor.mention)
                await channel.send(embed=e)
                await self._log_guild(message.guild, e, channel.id)
                return True

            if parsed.action == "clear":
                deleted = await channel.purge(limit=max(1, min(100, parsed.amount or 10)))
                await channel.send(f"🗑️ Deleted **{len(deleted)}** messages.", delete_after=6)
                return True

            if parsed.action == "slowmode":
                low = message.content.lower()
                if "disable" in low or "off" in low:
                    await channel.edit(slowmode_delay=0)
                    await channel.send("✅ Slowmode disabled.")
                else:
                    secs = self._extract_seconds(message.content) or 0
                    await channel.edit(slowmode_delay=max(1, min(21600, secs)))
                    await channel.send(f"🐌 Slowmode set to **{max(1, min(21600, secs))}s**.")
                return True

            if parsed.action in {"lock", "unlock"}:
                target = parsed.target_channel or channel
                send_messages = False if parsed.action == "lock" else None
                await target.set_permissions(message.guild.default_role, send_messages=send_messages, reason=reason)
                title = "🔒 Channel Locked" if parsed.action == "lock" else "🔓 Channel Unlocked"
                await channel.send(f"{title} — {target.mention}")
                return True

            if parsed.action == "case" and parsed.case_number is not None:
                gid = str(message.guild.id)
                c = self.mod_data.get("cases", {}).get(gid, {}).get("by_number", {}).get(str(parsed.case_number))
                if not c:
                    await channel.send("❌ Case not found.")
                    return True
                e = discord.Embed(title=f"📋 Case #{parsed.case_number}", color=COLOR_INFO)
                e.add_field(name="Type", value=c.get("type", "unknown"))
                e.add_field(name="User", value=c.get("user", "unknown"))
                e.add_field(name="Moderator", value=c.get("moderator", "unknown"))
                e.add_field(name="Reason", value=c.get("reason", "No reason"), inline=False)
                e.add_field(name="Timestamp", value=c.get("timestamp", "unknown"), inline=False)
                await channel.send(embed=e)
                return True

            if parsed.action == "userinfo":
                target = user or actor
                gid = str(message.guild.id)
                uid = str(target.id)
                warn_count = len(self.mod_data.get("warns", {}).get(gid, {}).get(uid, []))
                cases_db = self.mod_data.get("cases", {}).get(gid, {}).get("by_number", {})
                case_count = sum(1 for v in cases_db.values() if str(v.get("user_id")) == uid)
                roles = [r.mention for r in target.roles[-10:] if r != message.guild.default_role]
                e = discord.Embed(title=f"ℹ️ User Info — {target}", color=COLOR_INFO)
                e.add_field(name="ID", value=str(target.id))
                e.add_field(name="Display", value=target.display_name)
                e.add_field(name="Created", value=target.created_at.strftime('%Y-%m-%d'))
                e.add_field(name="Joined", value=target.joined_at.strftime('%Y-%m-%d') if target.joined_at else "Unknown")
                e.add_field(name="Timeout", value="Yes" if target.is_timed_out() else "No")
                e.add_field(name="Warns", value=str(warn_count))
                e.add_field(name="Cases", value=str(case_count))
                e.add_field(name="Roles", value=" ".join(roles) if roles else "None", inline=False)
                await channel.send(embed=e)
                return True

            if parsed.action == "massban":
                ids = parsed.target_user_ids[:10]
                ok, fail = 0, 0
                for uid in ids:
                    try:
                        user_obj = await self.bot.fetch_user(uid)
                        await message.guild.ban(user_obj, reason=f"{actor}: {reason}")
                        self._add_case(message.guild.id, "massban", uid, str(user_obj), actor.id, str(actor), reason)
                        ok += 1
                    except Exception:
                        fail += 1
                self._save()
                await channel.send(f"🔨 Massban finished — ✅ {ok} succeeded, ❌ {fail} failed.")
                return True

            if parsed.action == "note":
                if not await self._check_premium_from_message(channel, message.guild, actor):
                    return True
                gid, uid = str(message.guild.id), str(user.id)
                if parsed.note_action == "view":
                    notes = self.mod_data.get("notes", {}).get(gid, {}).get(uid, [])
                    if not notes:
                        await channel.send(f"📋 No notes for {user.mention}.")
                        return True
                    e = discord.Embed(title=f"📝 Mod Notes — {user}", color=COLOR_INFO)
                    for i, n in enumerate(notes[-10:], 1):
                        e.add_field(name=f"Note {i} — {n['timestamp'][:10]} by {n['author']}", value=n['text'][:500], inline=False)
                    await channel.send(embed=e)
                    return True
                if parsed.note_action == "clear":
                    self.mod_data.setdefault("notes", {}).setdefault(gid, {})[uid] = []
                    self._save()
                    await channel.send(f"✅ Notes cleared for {user.mention}.")
                    return True
                self.mod_data.setdefault("notes", {}).setdefault(gid, {}).setdefault(uid, []).append({
                    "text": parsed.note_text or reason,
                    "author": str(actor),
                    "author_id": actor.id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                self._save()
                await channel.send(f"📝 Note added for {user.mention}.")
                return True

        except discord.NotFound:
            await channel.send("❌ That user isn't banned.", delete_after=8)
            return True
        except discord.Forbidden:
            await channel.send("❌ I don't have permission for that moderation action.", delete_after=8)
            return True
        except Exception as ex:
            print(f"[NLP MOD] {ex}")
            await channel.send("❌ Couldn't run that moderation action.", delete_after=8)
            return True

        return False

    async def _check_premium_from_message(self, channel: discord.abc.Messageable, guild: discord.Guild, actor: discord.Member) -> bool:
        try:
            from usage_manager import get_tier_from_message
            class _Pseudo:
                def __init__(self, guild, user):
                    self.guild = guild
                    self.user = user
            tier = get_tier_from_message(_Pseudo(guild, actor))
        except Exception:
            tier = "free"
        if tier in ("premium", "gold", "enterprise"):
            return True
        await channel.send("🌟 This action requires Premium/Gold.")
        return False

    async def _check_premium(self, interaction: discord.Interaction) -> bool:
        try:
            from usage_manager import get_tier_from_message
            tier = get_tier_from_message(interaction)
        except Exception:
            tier = "free"
        if tier in ("premium", "gold", "enterprise"):
            return True
        embed = discord.Embed(
            title="🌟 Premium / Gold Required",
            description=(
                "This command is available for **Premium** and **Gold** subscribers.\n\n"
                "🔵 **Premium** — $10 / 2 months\n"
                "🟡 **Gold 👑** — $15 / 2 months\n\n"
                "🏢 **Enterprise** — custom limits/features, contact for pricing\n\n"
                "Contact `@aarav_2022` on Discord to upgrade!"
            ),
            color=COLOR_GOLD,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    def _get_tier(self, interaction_or_message) -> str:
        try:
            from usage_manager import get_tier_from_message
            return get_tier_from_message(interaction_or_message)
        except Exception:
            return "basic"

    def _get_feature_limit(self, tier: str, feature: str) -> int | None:
        caps = {
            "shadowban": {"premium": 5, "gold": 20, "enterprise": None},
            "sticky": {"premium": 1, "gold": 5, "enterprise": None},
        }
        if feature not in caps:
            return 0
        return caps[feature].get(tier, 0)

    async def _grant_verification_role(self, guild: discord.Guild, user: discord.abc.User):
        if not guild:
            return False, "❌ Server only."
        member = guild.get_member(user.id)
        if not isinstance(member, discord.Member):
            return False, "❌ Could not find you in this server."
        cfg = self._cfg(guild.id)
        role_id = cfg.get("verification_role_id")
        if not role_id:
            return False, "❌ Verification role is not configured."
        role = guild.get_role(int(role_id))
        if not role:
            return False, "❌ Verification role was deleted. Please re-run setup."
        try:
            await member.add_roles(role, reason="Member completed verification")
            try:
                if member.is_timed_out():
                    await member.timeout(None, reason="Member completed verification")
            except Exception:
                pass
            return True, "✅ You are verified. Welcome!"
        except discord.Forbidden:
            return False, "❌ I do not have permission to assign the verification role."
        except Exception:
            return False, "❌ Could not complete verification."

    async def _handle_verification_for_join(self, member: discord.Member, cfg: dict):
        channel = _resolve_verification_channel(member.guild, cfg.get("verification_channel_id"))
        if not channel:
            return

        try:
            if not member.is_timed_out():
                await member.timeout(timedelta(days=28), reason="Pending verification")
        except Exception:
            pass

        mode = cfg.get("verification_mode", "button")
        brand = (cfg.get("verification_branding") or "").strip()

        try:
            if mode == "math":
                difficulty = cfg.get("verification_difficulty", "easy")
                lim = 10 if difficulty == "easy" else 25 if difficulty == "medium" else 100
                a, b = random.randint(1, lim), random.randint(1, lim)
                answer = str(a + b)

                def check(m: discord.Message):
                    return m.author.id == member.id and m.channel.id == channel.id

                prompt = f"{member.mention} solve: **{a} + {b} = ?**"
                if brand:
                    prompt = f"**{brand}**\n{prompt}"
                await channel.send(prompt)

                try:
                    reply = await self.bot.wait_for("message", timeout=180, check=check)
                    if reply.content.strip() == answer:
                        await self._grant_verification_role(member.guild, member)
                        await channel.send(f"✅ {member.mention} verified!", delete_after=10)
                    else:
                        await channel.send(f"❌ {member.mention} wrong answer. Try again or ask staff.", delete_after=10)
                except asyncio.TimeoutError:
                    await channel.send(f"⌛ {member.mention} verification timed out. Run `/verification` setup or ask staff.", delete_after=10)
            else:
                text = cfg.get("verification_button_text", "✅ Verify")
                msg = f"{member.mention} click the button below to verify."
                if brand:
                    msg = f"**{brand}**\n{msg}"
                await channel.send(msg, view=VerifyButton(self, member.guild.id, member.id, text))
        except Exception as ex:
            print(f"[VERIFY] {ex}")

    # ── auto-mod: on_message ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if await self._handle_nl_mod(message):
            return

        cfg = self._cfg(message.guild.id)

        if cfg.get("shadowban_enabled") and message.author.id in cfg.get("shadowbanned_users", []):
            try:
                await message.delete()
            except Exception:
                pass
            return

        sticky_cfg = cfg.get("sticky_messages", {}) or {}
        sticky_state = sticky_cfg.get(str(message.channel.id)) if isinstance(sticky_cfg, dict) else None
        if sticky_state and sticky_state.get("message"):
            try:
                last_id = sticky_state.get("last_message_id")
                if last_id:
                    old = message.channel.get_partial_message(int(last_id))
                    await old.delete()
            except Exception:
                pass
            try:
                sent = await message.channel.send(sticky_state["message"])
                sticky_state["last_message_id"] = sent.id
                cfg["sticky_messages"][str(message.channel.id)] = sticky_state
                self._save()
            except Exception:
                pass

        if cfg.get("adaptive_slowmode_enabled"):
            now_ts = datetime.now(timezone.utc).timestamp()
            key = (message.guild.id, message.channel.id)
            bucket = _channel_msg_tracker[key]
            bucket.append(now_ts)
            window = max(3, int(cfg.get("adaptive_threshold_seconds", 10)))
            threshold = max(3, int(cfg.get("adaptive_threshold_messages", 50)))
            recent = [t for t in bucket if now_ts - t <= window]
            if len(recent) >= threshold:
                delay = max(1, min(21600, int(cfg.get("adaptive_slowmode_seconds", 10))))
                cooldown = max(10, int(cfg.get("adaptive_cooldown_seconds", 30)))
                try:
                    if getattr(message.channel, "slowmode_delay", 0) != delay:
                        await message.channel.edit(slowmode_delay=delay, reason="Adaptive slowmode enabled")
                        await message.channel.send(f"🐌 Adaptive slowmode enabled: {delay}s", delete_after=8)
                    cfg.setdefault("_adaptive_last_trigger", {})[str(message.channel.id)] = now_ts
                    cfg.setdefault("_adaptive_last_delay", {})[str(message.channel.id)] = delay
                    cfg.setdefault("_adaptive_cooldown", {})[str(message.channel.id)] = cooldown
                    self._save()
                except Exception:
                    pass

            last_trigger = (cfg.get("_adaptive_last_trigger", {}) or {}).get(str(message.channel.id))
            if last_trigger:
                cooldown = int((cfg.get("_adaptive_cooldown", {}) or {}).get(str(message.channel.id), 30))
                if now_ts - float(last_trigger) >= cooldown and len(recent) < max(1, threshold // 3):
                    try:
                        if getattr(message.channel, "slowmode_delay", 0) > 0:
                            await message.channel.edit(slowmode_delay=0, reason="Adaptive slowmode disabled")
                    except Exception:
                        pass
        if not cfg.get("setup_complete") or not cfg.get("automod_enabled"):
            return

        content  = message.content
        guild_id = message.guild.id
        user_id  = message.author.id
        now_ts   = datetime.now(timezone.utc).timestamp()

        exempt_roles = set(cfg.get("automod_exempt_roles", []))
        if isinstance(message.author, discord.Member) and exempt_roles:
            if any(role.id in exempt_roles for role in message.author.roles):
                return

        cl = content.lower()
        for word in cfg.get("bad_words", []):
            clean_word = word.lower().strip()
            if not clean_word:
                continue
            if re.search(rf"(?<!\w){re.escape(clean_word)}(?!\w)", cl, re.IGNORECASE):
                try:
                    await message.delete()
                    await message.channel.send(
                        f"⚠️ {message.author.mention} that message was removed.", delete_after=6
                    )
                    e = discord.Embed(title="🤬 Bad Word Removed", color=COLOR_DANGER,
                                     timestamp=datetime.now(timezone.utc))
                    e.add_field(name="User",    value=f"{message.author} (`{user_id}`)")
                    e.add_field(name="Channel", value=message.channel.mention)
                    e.add_field(name="Trigger", value=f"||{word}||")
                    await self._log_guild(message.guild, e, message.channel.id)
                except Exception as ex:
                    print(f"[AUTOMOD BAD WORD] {ex}")
                return

        if not cfg.get("links_allowed_server", True):
            if re.search(r"https?://\S+|www\.\S+|discord\.gg/\S+", content, re.IGNORECASE):
                allowed_chs   = [str(c) for c in cfg.get("link_allowed_channels", [])]
                allowed_roles = cfg.get("link_allowed_roles", [])
                in_allowed_ch = str(message.channel.id) in allowed_chs
                has_bypass    = isinstance(message.author, discord.Member) and \
                                any(r.id in allowed_roles for r in message.author.roles)
                if not in_allowed_ch and not has_bypass:
                    try:
                        await message.delete()
                        await message.channel.send(
                            f"🔗 {message.author.mention} links are not allowed here.", delete_after=6
                        )
                        e = discord.Embed(title="🔗 Link Blocked", color=0xFFA500,
                                         timestamp=datetime.now(timezone.utc))
                        e.add_field(name="User",    value=f"{message.author} (`{user_id}`)")
                        e.add_field(name="Channel", value=message.channel.mention)
                        await self._log_guild(message.guild, e, message.channel.id)
                    except Exception as ex:
                        print(f"[AUTOMOD LINK] {ex}")
                    return

        if cfg.get("anti_spam"):
            bucket = _spam_tracker[guild_id][user_id]
            bucket.append(now_ts)
            window = cfg.get("spam_seconds", 5)
            limit  = cfg.get("spam_messages", 5)
            recent = [t for t in bucket if now_ts - t <= window]
            if len(recent) >= limit:
                member = message.guild.get_member(user_id)
                if member and not member.guild_permissions.administrator:
                    try:
                        await member.timeout(timedelta(minutes=5), reason="AutoMod: spam")
                        try:
                            await message.channel.purge(
                                limit=15, check=lambda m: m.author.id == user_id
                            )
                        except Exception:
                            pass
                        await message.channel.send(
                            f"🚫 {member.mention} timed out **5 min** — slow down!", delete_after=10
                        )
                        e = discord.Embed(title="🚫 AutoMod: Spam Timeout", color=COLOR_DANGER,
                                         timestamp=datetime.now(timezone.utc))
                        e.add_field(name="User",    value=f"{member} (`{user_id}`)")
                        e.add_field(name="Channel", value=message.channel.mention)
                        e.add_field(name="Trigger", value=f"{len(recent)} msgs in {window}s")
                        await self._log_guild(message.guild, e, message.channel.id)
                        _spam_tracker[guild_id][user_id].clear()
                    except discord.Forbidden:
                        pass
                    except Exception as ex:
                        print(f"[AUTOMOD SPAM] {ex}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = self._cfg(member.guild.id)
        if cfg.get("verification_enabled"):
            asyncio.create_task(self._handle_verification_for_join(member, cfg))

        if not cfg.get("setup_complete") or not cfg.get("anti_raid"):
            return
        now_ts = datetime.now(timezone.utc).timestamp()
        bucket = _raid_tracker[member.guild.id]
        bucket.append(now_ts)
        window = cfg.get("raid_seconds", 10)
        limit  = cfg.get("raid_joins",   10)
        recent = [t for t in bucket if now_ts - t <= window]
        if len(recent) >= limit:
            locked = 0
            for ch in member.guild.text_channels:
                try:
                    await ch.set_permissions(member.guild.default_role,
                                             send_messages=False, reason="AutoMod: raid")
                    locked += 1
                except Exception:
                    pass
            e = discord.Embed(
                title="🚨 RAID DETECTED — Server Locked",
                description=(
                    f"**{len(recent)} members** joined in **{window}s**.\n"
                    f"**{locked} channels** locked.\n\n"
                    "Use `/unlock` to restore channels once the raid is over."
                ),
                color=COLOR_DANGER,
                timestamp=datetime.now(timezone.utc),
            )
            await self._log_guild(member.guild, e)
            _raid_tracker[member.guild.id].clear()

    async def _process_pending_unbans(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc)
        for gid_str, entries in self.mod_data.get("pending_unbans", {}).items():
            guild = self.bot.get_guild(int(gid_str))
            if not guild:
                continue
            remaining = []
            for entry in entries:
                unban_at = datetime.fromisoformat(entry["unban_at"])
                delay = (unban_at - now).total_seconds()
                if delay <= 0:
                    try:
                        user = await self.bot.fetch_user(entry["user_id"])
                        await guild.unban(user, reason="Temp ban expired")
                        print(f"[TEMPBAN] Unbanned {user} from {guild}")
                    except Exception as ex:
                        print(f"[TEMPBAN] {ex}")
                else:
                    remaining.append(entry)
                    asyncio.create_task(self._schedule_unban(int(gid_str), entry["user_id"], delay))
            self.mod_data["pending_unbans"][gid_str] = remaining
        self._save()

    async def _schedule_unban(self, guild_id: int, user_id: int, delay: float):
        await asyncio.sleep(delay)
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        try:
            user = await self.bot.fetch_user(user_id)
            await guild.unban(user, reason="Temp ban expired")
            gid_str = str(guild_id)
            if gid_str in self.mod_data.get("pending_unbans", {}):
                self.mod_data["pending_unbans"][gid_str] = [
                    e for e in self.mod_data["pending_unbans"][gid_str]
                    if e["user_id"] != user_id
                ]
                self._save()
        except Exception as ex:
            print(f"[TEMPBAN SCHEDULE] {ex}")

    # ──────────────────────────────────────────────────────────────────────────
    # /setup-moderation
    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="setup-moderation",
                          description="🛡️ Set up or reconfigure moderation for this server")
    async def setup_moderation(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("❌ Server only.", ephemeral=True)
            return
        member = interaction.user
        if not isinstance(member, discord.Member):
            return
        is_owner = interaction.guild.owner_id == member.id
        if not is_owner and not self._has_base_perms(member):
            embed = discord.Embed(
                title="❌ Permission Required",
                description=(
                    "Only the **server owner** or members with "
                    "**Ban / Kick / Timeout** permissions can run this command."
                ),
                color=COLOR_DANGER,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # ── Show permissions warning BEFORE the wizard starts ────────────────
        perms_warn = _perms_embed(interaction.guild)
        if perms_warn:
            await interaction.response.send_message(embed=perms_warn, ephemeral=True)
            # Small delay so the admin reads it, then send the wizard as a follow-up
            await asyncio.sleep(0.5)
            await interaction.followup.send(embed=emb_step1(), view=Step1View(
                f"{interaction.guild.id}_{interaction.user.id}"
            ))
            msg = await interaction.followup.send("_ _", wait=True)
            # Re-fetch the actual wizard message
            # (we send a dummy then get the real one)
            # Actually just get original_response for the wizard
            sk = f"{interaction.guild.id}_{interaction.user.id}"
            # Get the followup wizard message
            wiz_msg = await interaction.channel.fetch_message(
                (await interaction.original_response()).id
            )
        else:
            await interaction.response.send_message(embed=emb_step1(), view=Step1View(
                f"{interaction.guild.id}_{interaction.user.id}"
            ))
            wiz_msg = await interaction.original_response()

        sk = f"{interaction.guild.id}_{interaction.user.id}"
        setup_sessions[sk] = {
            "message": wiz_msg,
            "guild_id": interaction.guild.id,
            "user_id": interaction.user.id,
            "automod": False, "bad_words": [],
            "automod_exempt_roles": [],
            "log_channels": [], "log_everywhere": False,
            "mod_roles": [],
            "links_allowed_server": True, "link_allowed_channels": [], "link_allowed_roles": [],
            "anti_spam": False, "spam_messages": 5, "spam_seconds": 5,
            "anti_raid": False, "raid_joins": 10, "raid_seconds": 10,
            "verification_enabled": False,
            "verification_mode": "button",
            "verification_channel_id": None,
            "verification_role_id": None,
            "verification_button_text": "✅ Verify",
            "verification_difficulty": "easy",
            "verification_branding": "",
            "shadowban_enabled": False,
            "shadowbanned_users": [],
            "sticky_messages": {},
            "adaptive_slowmode_enabled": False,
            "adaptive_threshold_messages": 50,
            "adaptive_threshold_seconds": 10,
            "adaptive_slowmode_seconds": 10,
            "adaptive_cooldown_seconds": 30,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # /automod
    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="automod", description="🛡️ Toggle auto-moderation on or off")
    @app_commands.describe(action="Enable or disable automod")
    @app_commands.choices(action=[
        app_commands.Choice(name="enable",  value="enable"),
        app_commands.Choice(name="disable", value="disable"),
    ])
    async def automod_slash(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        if not await self._gate(interaction):
            return
        self._cfg(interaction.guild.id)["automod_enabled"] = (action.value == "enable")
        self._save()
        if action.value == "enable":
            await interaction.response.send_message(
                "✅ **AutoMod enabled.** Watching for bad words, spam, raids, and link violations."
            )
        else:
            await interaction.response.send_message("⛔ **AutoMod disabled.**")

    @app_commands.command(name="verification", description="✅ Configure join verification (button or math)")
    @app_commands.describe(
        enable="Enable or disable verification",
        mode="Verification mode",
        channel="Channel where verification prompts are sent",
        role="Role to grant after successful verification",
        button_text="Custom verify button text (Gold+)",
        math_difficulty="Math difficulty: easy, medium, hard (Gold+)",
        branding="Enterprise custom branding text",
    )
    async def verification_slash(
        self,
        interaction: discord.Interaction,
        enable: bool,
        mode: Literal["button", "math"] = "button",
        channel: discord.TextChannel | None = None,
        role: discord.Role | None = None,
        button_text: str | None = None,
        math_difficulty: Literal["easy", "medium", "hard"] = "easy",
        branding: str | None = None,
    ):
        if not await self._gate(interaction):
            return
        cfg = self._cfg(interaction.guild.id)
        tier = self._get_tier(interaction)
        if button_text and tier not in {"gold", "enterprise"}:
            await interaction.response.send_message("❌ Custom button text requires Gold or Enterprise.", ephemeral=True)
            return
        if math_difficulty != "easy" and tier not in {"gold", "enterprise"}:
            await interaction.response.send_message("❌ Custom math difficulty requires Gold or Enterprise.", ephemeral=True)
            return
        if branding and tier != "enterprise":
            await interaction.response.send_message("❌ Branding is Enterprise-only.", ephemeral=True)
            return
        if enable and not channel:
            await interaction.response.send_message("❌ Provide a verification channel when enabling.", ephemeral=True)
            return
        if enable and not role:
            await interaction.response.send_message("❌ Provide a verification role when enabling.", ephemeral=True)
            return

        if enable and role and role.is_default():
            await interaction.response.send_message("❌ Verification role cannot be `@everyone`.", ephemeral=True)
            return

        if enable and role and interaction.guild.me and role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "❌ I cannot assign that role. Move my role above the verification role.",
                ephemeral=True,
            )
            return

        cfg["verification_enabled"] = enable
        cfg["verification_mode"] = mode
        cfg["verification_channel_id"] = channel.id if channel else None
        cfg["verification_role_id"] = role.id if role else None
        if button_text:
            cfg["verification_button_text"] = button_text[:80]
        cfg["verification_difficulty"] = math_difficulty
        if branding is not None:
            cfg["verification_branding"] = branding[:120]
        self._save()

        visibility_note = ""
        if role and channel:
            updated, failed = await _set_verification_visibility(
                interaction.guild, role, channel.id, enable
            )
            visibility_note = (
                f"\n🔒 Visibility gate {'enabled' if enable else 'disabled'} "
                f"on **{updated}** channel(s)"
                + (f" (**{failed}** failed, check bot perms)." if failed else ".")
            )

        await interaction.response.send_message(
            f"✅ Verification {'enabled' if enable else 'disabled'} | mode: **{cfg['verification_mode']}**\n"
            "ℹ️ Unverified users are hidden from channels except verification."
            f"{visibility_note}"
        )

    shadowban_group = app_commands.Group(name="shadowban", description="👻 Configure shadowban users")

    @shadowban_group.command(name="add", description="👻 Shadowban a user")
    @app_commands.describe(user="User to shadowban")
    async def shadowban_add(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._gate(interaction):
            return
        tier = self._get_tier(interaction)
        cap = self._get_feature_limit(tier, "shadowban")
        cfg = self._cfg(interaction.guild.id)
        users = cfg.setdefault("shadowbanned_users", [])
        if user.id in users:
            await interaction.response.send_message("ℹ️ User is already shadowbanned.", ephemeral=True)
            return
        if cap is not None and len(users) >= cap:
            await interaction.response.send_message(f"❌ {tier.title()} shadowban cap reached ({cap}).", ephemeral=True)
            return
        cfg["shadowban_enabled"] = True
        users.append(user.id)
        self._save()
        await interaction.response.send_message(f"✅ {user.mention} added to shadowban list.")

    @shadowban_group.command(name="remove", description="👻 Remove a user from shadowban")
    async def shadowban_remove(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._gate(interaction):
            return
        cfg = self._cfg(interaction.guild.id)
        users = cfg.setdefault("shadowbanned_users", [])
        if user.id in users:
            users.remove(user.id)
            self._save()
            await interaction.response.send_message(f"✅ Removed {user.mention} from shadowban list.")
            return
        await interaction.response.send_message("ℹ️ That user is not shadowbanned.", ephemeral=True)

    @shadowban_group.command(name="list", description="👻 Show shadowbanned users")
    async def shadowban_list(self, interaction: discord.Interaction):
        if not await self._gate(interaction):
            return
        cfg = self._cfg(interaction.guild.id)
        users = cfg.get("shadowbanned_users", [])
        if not users:
            await interaction.response.send_message("No shadowbanned users.", ephemeral=True)
            return
        await interaction.response.send_message("\n".join(f"• <@{uid}> (`{uid}`)" for uid in users[:50]), ephemeral=True)

    sticky_group = app_commands.Group(name="sticky", description="📌 Sticky message management")

    @sticky_group.command(name="set", description="📌 Set sticky message for a channel")
    async def sticky_set(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        if not await self._gate(interaction):
            return
        tier = self._get_tier(interaction)
        cap = self._get_feature_limit(tier, "sticky")
        cfg = self._cfg(interaction.guild.id)
        sticky = cfg.setdefault("sticky_messages", {})
        if str(channel.id) not in sticky and cap is not None and len(sticky) >= cap:
            await interaction.response.send_message(f"❌ {tier.title()} sticky cap reached ({cap}).", ephemeral=True)
            return
        sticky[str(channel.id)] = {"message": message[:1800], "last_message_id": None}
        self._save()
        await interaction.response.send_message(f"✅ Sticky message set for {channel.mention}.")

    @sticky_group.command(name="clear", description="📌 Remove sticky message from a channel")
    async def sticky_clear(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await self._gate(interaction):
            return
        cfg = self._cfg(interaction.guild.id)
        sticky = cfg.setdefault("sticky_messages", {})
        if str(channel.id) in sticky:
            sticky.pop(str(channel.id), None)
            self._save()
            await interaction.response.send_message(f"✅ Sticky cleared for {channel.mention}.")
            return
        await interaction.response.send_message("ℹ️ No sticky configured for that channel.", ephemeral=True)

    @sticky_group.command(name="list", description="📌 List sticky channels")
    async def sticky_list(self, interaction: discord.Interaction):
        if not await self._gate(interaction):
            return
        sticky = self._cfg(interaction.guild.id).get("sticky_messages", {}) or {}
        if not sticky:
            await interaction.response.send_message("No sticky messages configured.", ephemeral=True)
            return
        await interaction.response.send_message(
            "\n".join(f"• <#{cid}>" for cid in list(sticky.keys())[:50]), ephemeral=True
        )

    @app_commands.command(name="adaptive-slowmode", description="🐌 Configure adaptive slowmode")
    async def adaptive_slowmode_slash(
        self,
        interaction: discord.Interaction,
        enable: bool,
        threshold_messages: int = 50,
        threshold_seconds: int = 10,
        slowmode_seconds: int = 10,
        cooldown_seconds: int = 30,
    ):
        if not await self._gate(interaction):
            return
        tier = self._get_tier(interaction)
        if tier not in {"gold", "enterprise"}:
            await interaction.response.send_message("❌ Adaptive slowmode requires Gold or Enterprise.", ephemeral=True)
            return
        if tier != "enterprise" and (threshold_messages != 50 or threshold_seconds != 10 or slowmode_seconds != 10):
            await interaction.response.send_message("❌ Custom adaptive thresholds are Enterprise-only.", ephemeral=True)
            return
        cfg = self._cfg(interaction.guild.id)
        cfg["adaptive_slowmode_enabled"] = enable
        if tier == "enterprise":
            cfg["adaptive_threshold_messages"] = max(3, min(500, threshold_messages))
            cfg["adaptive_threshold_seconds"] = max(3, min(120, threshold_seconds))
            cfg["adaptive_slowmode_seconds"] = max(1, min(21600, slowmode_seconds))
            cfg["adaptive_cooldown_seconds"] = max(10, min(600, cooldown_seconds))
        self._save()
        await interaction.response.send_message(
            f"✅ Adaptive slowmode {'enabled' if enable else 'disabled'}"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # WARN SYSTEM
    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="warn", description="⚠️ Warn a member and log the reason")
    @app_commands.describe(user="Member to warn", reason="Reason for the warning")
    async def warn_slash(self, interaction: discord.Interaction,
                         user: discord.Member, reason: str = "No reason provided"):
        if not await self._gate(interaction):
            return
        if user.bot:
            await interaction.response.send_message("❌ Can't warn a bot.", ephemeral=True)
            return
        gid, uid = str(interaction.guild.id), str(user.id)
        self.mod_data.setdefault("warns", {}).setdefault(gid, {}).setdefault(uid, [])
        self.mod_data["warns"][gid][uid].append({
            "reason": reason, "moderator": str(interaction.user),
            "moderator_id": interaction.user.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        count = len(self.mod_data["warns"][gid][uid])
        case_n = self._add_case(interaction.guild.id, "warn", user.id, str(user),
                                interaction.user.id, str(interaction.user), reason)
        self._save()
        try:
            await user.send(
                f"⚠️ You were **warned** in **{interaction.guild.name}**.\n"
                f"**Reason:** {reason}  |  **Total warns:** {count}"
            )
        except Exception:
            pass
        e = discord.Embed(title="⚠️ Member Warned", color=COLOR_GOLD,
                          timestamp=datetime.now(timezone.utc))
        e.add_field(name="User",       value=f"{user.mention} (`{user.id}`)")
        e.add_field(name="Reason",     value=reason)
        e.add_field(name="Warn #",     value=count)
        e.add_field(name="Case #",     value=f"#{case_n}")
        e.add_field(name="Moderator",  value=interaction.user.mention)
        await interaction.response.send_message(embed=e)
        await self._log_guild(interaction.guild, e, interaction.channel.id)
        if count >= 3:
            try:
                await user.timeout(timedelta(minutes=10), reason="Auto: 3 warnings reached")
                await interaction.followup.send(
                    f"🚫 {user.mention} auto-timed out **10 min** — 3 warnings reached."
                )
            except Exception:
                pass

    @app_commands.command(name="warns", description="📋 View all warnings for a member")
    @app_commands.describe(user="Member to check")
    async def warns_slash(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._gate(interaction):
            return
        gid, uid = str(interaction.guild.id), str(user.id)
        warns = self.mod_data.get("warns", {}).get(gid, {}).get(uid, [])
        if not warns:
            await interaction.response.send_message(f"✅ {user.mention} has no warnings.")
            return
        e = discord.Embed(title=f"⚠️ Warnings — {user}", color=COLOR_GOLD)
        for i, w in enumerate(warns[-10:], 1):
            e.add_field(
                name=f"#{i} — {w['timestamp'][:10]}",
                value=f"**Reason:** {w['reason']}\n**By:** {w['moderator']}",
                inline=False,
            )
        e.set_footer(text=f"Total: {len(warns)} warning(s)")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="clearwarns", description="🗑️ Clear all warnings for a member")
    @app_commands.describe(user="Member to clear")
    async def clearwarns_slash(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._gate(interaction):
            return
        gid, uid = str(interaction.guild.id), str(user.id)
        self.mod_data.setdefault("warns", {}).setdefault(gid, {})[uid] = []
        self._save()
        await interaction.response.send_message(f"✅ All warnings cleared for {user.mention}.")

    # ──────────────────────────────────────────────────────────────────────────
    # BAN / UNBAN / KICK
    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="🔨 Ban a member from the server")
    @app_commands.describe(user="Member to ban (works even if they already left)", reason="Reason", delete_days="Days of messages to delete (0–7)")
    async def ban_slash(self, interaction: discord.Interaction,
                        user: discord.User, reason: str = "No reason provided",
                        delete_days: int = 0):
        if not await self._gate(interaction):
            return
        # Role hierarchy check only applies if the user is still in the server
        member = interaction.guild.get_member(user.id)
        if member is not None:
            if member.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
                await interaction.response.send_message("❌ Can't ban someone with equal or higher role.", ephemeral=True)
                return
        try: await user.send(f"🔨 You were **banned** from **{interaction.guild.name}**.\n**Reason:** {reason}")
        except Exception: pass
        try:
            await interaction.guild.ban(user, reason=f"{interaction.user}: {reason}",
                                        delete_message_days=max(0, min(7, delete_days)))
            case_n = self._add_case(interaction.guild.id, "ban", user.id, str(user),
                                    interaction.user.id, str(interaction.user), reason)
            e = discord.Embed(title="🔨 Member Banned", color=COLOR_DANGER,
                              timestamp=datetime.now(timezone.utc))
            e.add_field(name="User",      value=f"{user} (`{user.id}`)")
            e.add_field(name="Reason",    value=reason)
            e.add_field(name="Case #",    value=f"#{case_n}")
            e.add_field(name="Moderator", value=interaction.user.mention)
            await interaction.response.send_message(embed=e)
            await self._log_guild(interaction.guild, e, interaction.channel.id)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to ban this user.", ephemeral=True)
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"❌ Ban failed: {exc.text}", ephemeral=True)

    @ban_slash.error
    async def ban_slash_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.TransformerError):
            await interaction.response.send_message(
                "❌ Could not find that user. They may have already left the server — "
                "try passing their **user ID** directly instead.",
                ephemeral=True,
            )
        else:
            raise error

    @app_commands.command(name="unban", description="🔓 Unban a user by their Discord ID")
    @app_commands.describe(user_id="The Discord user ID to unban", reason="Reason")
    async def unban_slash(self, interaction: discord.Interaction,
                          user_id: str, reason: str = "No reason provided"):
        if not await self._gate(interaction):
            return
        if not user_id.isdigit():
            await interaction.response.send_message("❌ User ID must be a number.", ephemeral=True)
            return
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=reason)
            e = discord.Embed(title="🔓 Member Unbanned", color=COLOR_SUCCESS,
                              timestamp=datetime.now(timezone.utc))
            e.add_field(name="User",      value=f"{user} (`{user.id}`)")
            e.add_field(name="Reason",    value=reason)
            e.add_field(name="Moderator", value=interaction.user.mention)
            await interaction.response.send_message(embed=e)
            await self._log_guild(interaction.guild, e, interaction.channel.id)
        except discord.NotFound:
            await interaction.response.send_message("❌ That user isn't banned.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ No permission to unban.", ephemeral=True)

    @app_commands.command(name="modkick", description="👢 Kick a member from the server")
    @app_commands.describe(user="Member to kick", reason="Reason")
    async def modkick_slash(self, interaction: discord.Interaction,
                            user: discord.Member, reason: str = "No reason provided"):
        if not await self._gate(interaction):
            return
        if user.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
            await interaction.response.send_message("❌ Can't kick someone with equal or higher role.", ephemeral=True)
            return
        try: await user.send(f"👢 You were **kicked** from **{interaction.guild.name}**.\n**Reason:** {reason}")
        except Exception: pass
        try:
            await user.kick(reason=f"{interaction.user}: {reason}")
            case_n = self._add_case(interaction.guild.id, "kick", user.id, str(user),
                                    interaction.user.id, str(interaction.user), reason)
            e = discord.Embed(title="👢 Member Kicked", color=0xFF4500,
                              timestamp=datetime.now(timezone.utc))
            e.add_field(name="User",      value=f"{user} (`{user.id}`)")
            e.add_field(name="Reason",    value=reason)
            e.add_field(name="Case #",    value=f"#{case_n}")
            e.add_field(name="Moderator", value=interaction.user.mention)
            await interaction.response.send_message(embed=e)
            await self._log_guild(interaction.guild, e, interaction.channel.id)
        except discord.Forbidden:
            await interaction.response.send_message("❌ No permission to kick.", ephemeral=True)

    @modkick_slash.error
    async def modkick_slash_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.TransformerError):
            await interaction.response.send_message(
                "❌ That user is not in this server — they may have already been kicked or left on their own.",
                ephemeral=True,
            )
        else:
            raise error

    # ──────────────────────────────────────────────────────────────────────────
    # MUTE / UNMUTE
    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="mute", description="🔇 Timeout (mute) a member for a set duration")
    @app_commands.describe(user="Member to mute", minutes="Duration in minutes (1–40320)", reason="Reason")
    async def mute_slash(self, interaction: discord.Interaction,
                         user: discord.Member, minutes: int = 10,
                         reason: str = "No reason provided"):
        if not await self._gate(interaction):
            return
        if user.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
            await interaction.response.send_message("❌ Can't mute someone with equal or higher role.", ephemeral=True)
            return
        dur = max(1, min(40320, minutes))
        try:
            await user.timeout(timedelta(minutes=dur), reason=reason)
            case_n = self._add_case(interaction.guild.id, "mute", user.id, str(user),
                                    interaction.user.id, str(interaction.user), reason,
                                    {"minutes": dur})
            try:
                await user.send(
                    f"🔇 Muted in **{interaction.guild.name}** for **{dur} min**.\n**Reason:** {reason}"
                )
            except Exception: pass
            e = discord.Embed(title="🔇 Member Muted", color=0xFF8C00,
                              timestamp=datetime.now(timezone.utc))
            e.add_field(name="User",      value=f"{user.mention} (`{user.id}`)")
            e.add_field(name="Duration",  value=f"{dur} minutes")
            e.add_field(name="Reason",    value=reason)
            e.add_field(name="Case #",    value=f"#{case_n}")
            e.add_field(name="Moderator", value=interaction.user.mention)
            await interaction.response.send_message(embed=e)
            await self._log_guild(interaction.guild, e, interaction.channel.id)
        except discord.Forbidden:
            await interaction.response.send_message("❌ No permission to timeout.", ephemeral=True)

    @app_commands.command(name="unmute", description="🔊 Remove a timeout from a member")
    @app_commands.describe(user="Member to unmute", reason="Reason")
    async def unmute_slash(self, interaction: discord.Interaction,
                           user: discord.Member, reason: str = "No reason provided"):
        if not await self._gate(interaction):
            return
        try:
            await user.timeout(None, reason=reason)
            e = discord.Embed(title="🔊 Member Unmuted", color=COLOR_SUCCESS,
                              timestamp=datetime.now(timezone.utc))
            e.add_field(name="User",      value=f"{user.mention} (`{user.id}`)")
            e.add_field(name="Moderator", value=interaction.user.mention)
            await interaction.response.send_message(embed=e)
            await self._log_guild(interaction.guild, e, interaction.channel.id)
        except discord.Forbidden:
            await interaction.response.send_message("❌ No permission to unmute.", ephemeral=True)

    # ──────────────────────────────────────────────────────────────────────────
    # CHANNEL MANAGEMENT
    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="clear", description="🗑️ Bulk-delete messages in this channel")
    @app_commands.describe(amount="Number to delete (1–100)")
    async def clear_slash(self, interaction: discord.Interaction, amount: int = 10):
        if not await self._gate(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=max(1, min(100, amount)))
        await interaction.followup.send(f"🗑️ Deleted **{len(deleted)}** messages.", ephemeral=True)
        e = discord.Embed(title="🗑️ Messages Cleared", color=COLOR_GREY,
                          timestamp=datetime.now(timezone.utc))
        e.add_field(name="Channel",   value=interaction.channel.mention)
        e.add_field(name="Count",     value=len(deleted))
        e.add_field(name="Moderator", value=interaction.user.mention)
        await self._log_guild(interaction.guild, e, interaction.channel.id)

    @app_commands.command(name="slowmode", description="🐌 Enable or disable slowmode for this channel")
    @app_commands.describe(
        enable="Choose whether to enable or disable slowmode",
        duration="Required when enabling (seconds, max 21600)",
    )
    async def slowmode_slash(
        self,
        interaction: discord.Interaction,
        enable: Literal["enable", "disable"],
        duration: Optional[int] = None,
    ):
        if not await self._gate(interaction):
            return

        if enable == "disable":
            await interaction.channel.edit(slowmode_delay=0)
            await interaction.response.send_message("✅ Slowmode **disabled**.")
            return

        if duration is None:
            await interaction.response.send_message(
                "❌ Please provide a **duration** (in seconds) when enabling slowmode.",
                ephemeral=True,
            )
            return

        delay = max(1, min(21600, duration))
        await interaction.channel.edit(slowmode_delay=delay)
        await interaction.response.send_message(f"🐌 Slowmode set to **{delay}s**.")

    @app_commands.command(name="lock", description="🔒 Prevent @everyone from sending messages")
    @app_commands.describe(channel="Channel to lock (default: current)", reason="Reason")
    async def lock_slash(self, interaction: discord.Interaction,
                         channel: Optional[discord.TextChannel] = None,
                         reason: str = "No reason provided"):
        if not await self._gate(interaction):
            return
        target = channel or interaction.channel
        await target.set_permissions(interaction.guild.default_role, send_messages=False, reason=reason)
        e = discord.Embed(title="🔒 Channel Locked", color=COLOR_DANGER,
                          timestamp=datetime.now(timezone.utc))
        e.add_field(name="Channel",   value=target.mention)
        e.add_field(name="Reason",    value=reason)
        e.add_field(name="Moderator", value=interaction.user.mention)
        await interaction.response.send_message(embed=e)
        await self._log_guild(interaction.guild, e, target.id)

    @app_commands.command(name="unlock", description="🔓 Restore @everyone's ability to send messages")
    @app_commands.describe(channel="Channel to unlock (default: current)", reason="Reason")
    async def unlock_slash(self, interaction: discord.Interaction,
                           channel: Optional[discord.TextChannel] = None,
                           reason: str = "No reason provided"):
        if not await self._gate(interaction):
            return
        target = channel or interaction.channel
        await target.set_permissions(interaction.guild.default_role, send_messages=None, reason=reason)
        e = discord.Embed(title="🔓 Channel Unlocked", color=COLOR_SUCCESS,
                          timestamp=datetime.now(timezone.utc))
        e.add_field(name="Channel",   value=target.mention)
        e.add_field(name="Moderator", value=interaction.user.mention)
        await interaction.response.send_message(embed=e)
        await self._log_guild(interaction.guild, e, target.id)

    # ──────────────────────────────────────────────────────────────────────────
    # USER INFO + CASE LOOKUP
    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="userinfo", description="ℹ️ Detailed info about a server member")
    @app_commands.describe(user="Member to inspect (default: yourself)")
    async def userinfo_slash(self, interaction: discord.Interaction,
                             user: Optional[discord.Member] = None):
        if not await self._gate(interaction):
            return
        target = user or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message("❌ Server members only.", ephemeral=True)
            return
        gid, uid   = str(interaction.guild.id), str(target.id)
        warn_count = len(self.mod_data.get("warns",{}).get(gid,{}).get(uid,[]))
        cases_data = self.mod_data.get("cases",{}).get(gid,{}).get("by_number",{})
        user_cases = [c for c in cases_data.values() if str(c.get("user_id")) == uid]
        roles      = [r.mention for r in reversed(target.roles[1:])]
        e = discord.Embed(title=f"ℹ️ {target}", color=target.color if target.color.value else COLOR_INFO,
                          timestamp=datetime.now(timezone.utc))
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="ID",             value=target.id,                              inline=True)
        e.add_field(name="Display Name",   value=target.display_name,                   inline=True)
        e.add_field(name="Bot",            value="🤖 Yes" if target.bot else "No",       inline=True)
        e.add_field(name="Account Created",value=target.created_at.strftime("%Y-%m-%d"), inline=True)
        e.add_field(name="Joined Server",  value=(target.joined_at.strftime("%Y-%m-%d")
                                                   if target.joined_at else "Unknown"),  inline=True)
        e.add_field(name="Timed Out",      value="Yes ⏰" if target.timed_out_until else "No", inline=True)
        e.add_field(name="⚠️ Warns",       value=warn_count,                             inline=True)
        e.add_field(name="📋 Cases",       value=len(user_cases),                        inline=True)
        e.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles[:10]) or "None", inline=False)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="case", description="📋 Look up a mod action by case number")
    @app_commands.describe(number="The case number to look up")
    async def case_slash(self, interaction: discord.Interaction, number: int):
        if not await self._gate(interaction):
            return
        gid   = str(interaction.guild.id)
        cases = self.mod_data.get("cases", {}).get(gid, {}).get("by_number", {})
        case  = cases.get(str(number))
        if not case:
            await interaction.response.send_message(
                f"❌ Case #{number} not found. Cases go from #1 to "
                f"#{self.mod_data.get('cases',{}).get(gid,{}).get('next_case',1)-1}.",
                ephemeral=True,
            )
            return
        type_icons = {"ban":"🔨","kick":"👢","warn":"⚠️","mute":"🔇","tempban":"⏱️",
                      "massban":"🔨","unban":"🔓","note":"📝"}
        icon = type_icons.get(case["type"], "📋")
        e = discord.Embed(
            title=f"{icon} Case #{number} — {case['type'].upper()}",
            color=COLOR_INFO,
            timestamp=datetime.fromisoformat(case["timestamp"]),
        )
        e.add_field(name="User",      value=f"{case['user']} (`{case['user_id']}`)")
        e.add_field(name="Moderator", value=f"{case['moderator']} (`{case['moderator_id']}`)")
        e.add_field(name="Reason",    value=case["reason"], inline=False)
        if case.get("extra"):
            for k, v in case["extra"].items():
                e.add_field(name=k.title(), value=str(v), inline=True)
        e.set_footer(text=f"Case #{number}  •  {case['timestamp'][:10]}")
        await interaction.response.send_message(embed=e)

    # ──────────────────────────────────────────────────────────────────────────
    # 🌟 PREMIUM COMMANDS
    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="tempban",
        description="⏱️ [Premium] Temporarily ban a member — they're auto-unbanned after the duration")
    @app_commands.describe(user="Member to temp-ban", duration="Duration: e.g. 30m, 6h, 7d", reason="Reason")
    async def tempban_slash(self, interaction: discord.Interaction,
                            user: discord.Member, duration: str,
                            reason: str = "Temporary ban"):
        if not await self._gate(interaction):
            return
        if not await self._check_premium(interaction):
            return
        td = _parse_duration(duration)
        if not td:
            await interaction.response.send_message(
                "❌ Invalid duration. Use `30m`, `6h`, `2d` etc.", ephemeral=True
            )
            return
        if user.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
            await interaction.response.send_message("❌ Can't ban someone with equal or higher role.", ephemeral=True)
            return
        unban_at = (datetime.now(timezone.utc) + td).isoformat()
        try:
            await user.send(
                f"⏱️ You were **temp-banned** from **{interaction.guild.name}**.\n"
                f"**Duration:** {duration}  |  **Reason:** {reason}\n"
                f"You will be automatically unbanned."
            )
        except Exception: pass
        try:
            await user.ban(reason=f"{interaction.user}: [TEMPBAN {duration}] {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ No permission to ban.", ephemeral=True)
            return
        gid_str = str(interaction.guild.id)
        self.mod_data.setdefault("pending_unbans", {}).setdefault(gid_str, []).append(
            {"user_id": user.id, "unban_at": unban_at}
        )
        case_n = self._add_case(interaction.guild.id, "tempban", user.id, str(user),
                                interaction.user.id, str(interaction.user), reason,
                                {"duration": duration, "unban_at": unban_at})
        self._save()
        asyncio.create_task(self._schedule_unban(interaction.guild.id, user.id, td.total_seconds()))
        e = discord.Embed(title="⏱️ Member Temp-Banned", color=COLOR_DANGER,
                          timestamp=datetime.now(timezone.utc))
        e.add_field(name="User",      value=f"{user} (`{user.id}`)")
        e.add_field(name="Duration",  value=duration)
        e.add_field(name="Unban At",  value=unban_at[:16].replace("T", " ") + " UTC")
        e.add_field(name="Reason",    value=reason)
        e.add_field(name="Case #",    value=f"#{case_n}")
        e.add_field(name="Moderator", value=interaction.user.mention)
        await interaction.response.send_message(embed=e)
        await self._log_guild(interaction.guild, e, interaction.channel.id)

    @app_commands.command(name="massban",
        description="🔨 [Premium] Ban up to 10 users at once via a modal (ID list)")
    async def massban_slash(self, interaction: discord.Interaction):
        if not await self._gate(interaction):
            return
        if not await self._check_premium(interaction):
            return
        await interaction.response.send_modal(MassBanModal(self, interaction.guild))

    @app_commands.command(name="modstats",
        description="📊 [Premium] Detailed moderation statistics for this server")
    async def modstats_slash(self, interaction: discord.Interaction):
        if not await self._gate(interaction):
            return
        if not await self._check_premium(interaction):
            return
        await interaction.response.defer()
        gid       = str(interaction.guild.id)
        warns_db  = self.mod_data.get("warns", {}).get(gid, {})
        cases_db  = self.mod_data.get("cases", {}).get(gid, {}).get("by_number", {})
        now       = datetime.now(timezone.utc)
        month_ago = (now - timedelta(days=30)).isoformat()

        type_counts:  dict = defaultdict(int)
        mod_counts:   dict = defaultdict(int)
        month_counts: dict = defaultdict(int)
        for c in cases_db.values():
            type_counts[c["type"]] += 1
            mod_counts[c["moderator"]] += 1
            if c["timestamp"] >= month_ago:
                month_counts[c["type"]] += 1

        top_warned = sorted(warns_db.items(), key=lambda x: len(x[1]), reverse=True)[:5]
        top_mods   = sorted(mod_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        e = discord.Embed(title=f"📊 Moderation Stats — {interaction.guild.name}",
                          color=COLOR_INFO, timestamp=now)
        action_lines = []
        for t, icon in [("ban","🔨"),("kick","👢"),("warn","⚠️"),("mute","🔇"),
                        ("tempban","⏱️"),("massban","🔨")]:
            total = type_counts.get(t, 0)
            month = month_counts.get(t, 0)
            if total > 0:
                action_lines.append(f"{icon} **{t.title()}s:** {total} total, {month} this month")
        e.add_field(name="📋 Action Counts",
                    value="\n".join(action_lines) or "No actions yet.", inline=False)
        if top_warned:
            lines = []
            for uid, wlist in top_warned:
                try:
                    user = interaction.guild.get_member(int(uid)) or await self.bot.fetch_user(int(uid))
                    lines.append(f"{user} — **{len(wlist)}** warns")
                except Exception:
                    lines.append(f"`{uid}` — **{len(wlist)}** warns")
            e.add_field(name="🏆 Most Warned Members", value="\n".join(lines), inline=False)
        if top_mods:
            e.add_field(
                name="👮 Most Active Moderators",
                value="\n".join(f"{m} — **{n}** actions" for m, n in top_mods),
                inline=False,
            )
        total_warns = sum(len(v) for v in warns_db.values())
        total_cases = len(cases_db)
        e.add_field(name="📈 Totals",
                    value=f"**{total_warns}** total warns  •  **{total_cases}** total cases", inline=False)
        await interaction.followup.send(embed=e)

    note_group = app_commands.Group(
        name="note",
        description="📝 [Premium] Private moderator notes on server members",
    )

    @note_group.command(name="add", description="📝 Add a private mod note to a member")
    @app_commands.describe(user="Member to note", text="The note content")
    async def note_add(self, interaction: discord.Interaction,
                       user: discord.Member, text: str):
        if not await self._gate(interaction):
            return
        if not await self._check_premium(interaction):
            return
        gid, uid = str(interaction.guild.id), str(user.id)
        self.mod_data.setdefault("notes", {}).setdefault(gid, {}).setdefault(uid, [])
        self.mod_data["notes"][gid][uid].append({
            "text": text, "author": str(interaction.user),
            "author_id": interaction.user.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._save()
        await interaction.response.send_message(
            f"📝 Note added for {user.mention}. Only moderators can see these.", ephemeral=True
        )

    @note_group.command(name="view", description="📋 View all notes for a member")
    @app_commands.describe(user="Member to view notes for")
    async def note_view(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._gate(interaction):
            return
        if not await self._check_premium(interaction):
            return
        gid, uid = str(interaction.guild.id), str(user.id)
        notes = self.mod_data.get("notes", {}).get(gid, {}).get(uid, [])
        if not notes:
            await interaction.response.send_message(f"📋 No notes for {user.mention}.", ephemeral=True)
            return
        e = discord.Embed(title=f"📝 Mod Notes — {user}", color=COLOR_INFO)
        for i, n in enumerate(notes[-10:], 1):
            e.add_field(
                name=f"Note {i} — {n['timestamp'][:10]} by {n['author']}",
                value=n["text"][:500],
                inline=False,
            )
        e.set_footer(text=f"Total: {len(notes)} note(s)  •  Visible to mods only")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @note_group.command(name="clear", description="🗑️ Delete all notes for a member")
    @app_commands.describe(user="Member to clear notes for")
    async def note_clear(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._gate(interaction):
            return
        if not await self._check_premium(interaction):
            return
        gid, uid = str(interaction.guild.id), str(user.id)
        self.mod_data.setdefault("notes", {}).setdefault(gid, {})[uid] = []
        self._save()
        await interaction.response.send_message(f"✅ Notes cleared for {user.mention}.", ephemeral=True)


async def setup(bot: commands.Bot):
    cog = ModerationCog(bot)
    await bot.add_cog(cog)
    print("[COG] Loaded ModerationCog")
