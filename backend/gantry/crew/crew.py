"""The AI production crew, organised like a real broadcast team.

    stats desk  ->  director  ->  commentator, one per feed  ->  voice, one per feed

Each role is an executor in a Microsoft Agent Framework workflow (roles.py).
The stats desk, director and commentators are agents on Microsoft Foundry;
the voices are Azure AI Speech. They share one booth (booth.py) and hand work
to each other as messages. Every number and name they use comes from code
(desk.py, match_stats.py).

The crew watches the match 15 seconds ahead of the viewers, the way a TV
broadcast runs on a short delay. A big moment is covered by two workflow runs
at once: the call, which goes straight to the commentators, and the analysis,
which waits for the stats desk and the director and goes out over the replay.
If a model is slow or fails, the show goes on: the director falls back to its
own rules and a commentator to a prepared line.
"""

from __future__ import annotations

import asyncio
import os

from agent_framework import Agent, WorkflowBuilder
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import DefaultAzureCredential

from ..ai.azure import setting
from .booth import Booth
from .feeds import Feed
from .house import house_rules, team_sheet
from .roles import CommentatorExecutor, DirectorExecutor, StatsDeskExecutor, VoiceExecutor, opts
from .voice import Voices

DELAY_TICKS = 150             # the broadcast runs 15 seconds behind the crew

# each role on the cheapest model that does its job well; any of them can be changed in .env
ROLES = {
    "call": ("GANTRY_MODEL_CALL", "gpt-5.4-mini"),       # the instant call on a big moment: few, short, must be right
    "lines": ("GANTRY_MODEL_LINES", "gpt-5.4-mini"),     # every other line on air: the words are the product
    "desk": ("GANTRY_MODEL_DESK", "gpt-5-mini"),
    "director": ("GANTRY_MODEL_DIRECTOR", "gpt-5-mini"),
    "editor": ("GANTRY_MODEL_EDITOR", "gpt-5-mini"),
    "producer": ("GANTRY_MODEL_PRODUCER", "gpt-5-mini"),
}


class Crew:
    """Model clients and voices, created once per server and shared by every broadcast session."""

    def __init__(self):
        self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        # without a Foundry project the produced broadcast still plays; only live work needs the models
        self.endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
        self.ready = bool(self.endpoint)
        self.models = {role: os.environ.get(env, default) for role, (env, default) in ROLES.items()}
        self._clients: dict[str, FoundryChatClient] = {}
        self.voices = Voices()
        self._warm = asyncio.Lock()
        self._warmed = False

    def client(self, role: str) -> FoundryChatClient:
        if not self.ready:
            setting("AZURE_AI_PROJECT_ENDPOINT")   # says which setting is missing
        model = self.models[role]
        if model not in self._clients:
            self._clients[model] = FoundryChatClient(project_endpoint=self.endpoint, model=model, credential=self.credential)
        return self._clients[model]

    def agents(self, booth: Booth, meta: dict) -> dict:
        def commentator(feed: Feed, role: str) -> Agent:
            instructions = "\n\n".join([
                f"{feed.persona_for(meta)}\nAudience: {feed.audience}\nYou are live on air, speaking {feed.lang.name}.",
                house_rules(feed),
                team_sheet(feed, meta),
            ])
            return Agent(self.client(role), name=f"commentator_{feed.id}", instructions=instructions)

        desk_agent = Agent(
            self.client("desk"), name="stats_desk", tools=booth.desk.tools(lambda: booth.viewer_tick + DELAY_TICKS),
            instructions=("You are the stats desk of a live football broadcast. You receive a moment with facts from the "
                          "tracking system. Explain briefly why it matters for the match. You may call a tool or two for "
                          "context. Never state a name or number that did not come from the facts or a tool."))
        director = Agent(
            self.client("director"), name="director",
            instructions=("You are the director in the gallery of a live football broadcast that produces several "
                          "personalised feeds at once. You decide what each feed puts on air and when, keeping each one "
                          "right for its audience and never cluttered."))
        return {
            "desk": desk_agent, "director": director,
            "calls": {f.id: commentator(f, "call") for f in booth.feeds.values()},
            "lines": {f.id: commentator(f, "lines") for f in booth.feeds.values()},
            "editor": Agent(self.client("editor"), name="editor",
                            instructions=("You are the match editor of a live football broadcast. At half-time and "
                                          "full-time you cut the highlights package and write the report for each "
                                          "personalised feed, in its language and style.")),
        }

    def workflow(self, booth: Booth, agents: dict):
        desk = StatsDeskExecutor(booth, agents["desk"], self.models["desk"])
        director = DirectorExecutor(booth, agents["director"], self.models["director"])
        models = (self.models["call"], self.models["lines"])
        comms = [CommentatorExecutor(booth, f, agents["calls"][f], agents["lines"][f], models) for f in booth.feeds]
        voices = [VoiceExecutor(booth, f) for f in booth.feeds]
        build = WorkflowBuilder(name="gantry-crew", start_executor=desk).add_edge(desk, director)
        if len(comms) == 1:
            build.add_edge(director, comms[0])          # a viewer's own feed: one commentator
        else:
            build.add_multi_selection_edge_group(
                director, comms, selection_func=lambda reqs, ids: [i for i in ids if i[len("commentator_"):] in {r.feed for r in reqs.requests}])
        for c, v in zip(comms, voices):
            build.add_edge(c, v)
        return build.build()

    def editor_workflow(self, booth: Booth, agents: dict, total_ticks: int):
        """The editor works in its own workflow, alongside the live crew, so a long edit never holds up the show."""
        from .editor import EditorExecutor
        editor = EditorExecutor(booth, agents["editor"], total_ticks, self.models["editor"])
        return WorkflowBuilder(name="gantry-editor", start_executor=editor).build()

    async def trace(self):
        """Send the crew's traces (every workflow, executor, agent and model call) to the Application Insights
        connected to the Foundry project, where Foundry's Tracing view shows them. Off with GANTRY_TRACING=off."""
        if os.environ.get("GANTRY_TRACING", "on").lower() == "off" or not self.ready:
            return
        try:
            await self.client("call").configure_azure_monitor()
        except Exception as e:  # tracing is never allowed to stop the show
            import logging
            logging.getLogger("gantry").warning("tracing is off: %s", e)

    async def warm_up(self):
        """One tiny call per model, once per server, so the first live moment isn't slowed by cold connections."""
        async with self._warm:
            if self._warmed:
                return
            self._warmed = True

            async def ping(role):
                try:
                    a = Agent(self.client(role), name=f"warm_{role}", instructions="Reply with OK.")
                    await asyncio.wait_for(a.run("OK?", options=opts(self.models[role])), 20)
                except Exception:
                    pass
            roles = {self.models[r]: r for r in ("call", "lines")}.values()
            await asyncio.gather(*(ping(r) for r in roles))
