"""Plays one synthetic football match and records it at 10 frames per second.

Coordinates are metres. x runs along the pitch (0..105), y across it (0..68),
z is height. Each team's own frame of reference is `u`, the distance from its
own goal line towards the goal it attacks.

The engine is deliberately simple football: a team shape that slides with the
ball, a nearest-player press, runs in behind, and on-ball choices scored by
"how likely is this to work" times "how dangerous is the place it gets us".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .director import Director
from .squads import TEAMS, Player

DT = 0.1
HZ = 10
L, W = 105.0, 68.0
CY = W / 2
POST = 3.66
BAR = 2.44
BOX_DEPTH, BOX_HALF = 16.5, 20.16

PLAY, RESTART, KICKOFF, GOAL = 0, 1, 2, 3

# period, clock, ball x/y/z, owner slot, state, then x/y for the 22 slots
FRAME_HEAD = 7
FRAME_COLS = FRAME_HEAD + 44

RUN_WEIGHT = {"ST": 1.0, "RW": 1.0, "LW": 1.0, "RAM": 0.9, "LAM": 0.9, "CAM": 0.6,
              "RCM": 0.35, "LCM": 0.35, "RB": 0.25, "LB": 0.25}


def threat(u, y):
    """Rough chance of scoring soon from a spot, for the team attacking from u."""
    d = np.hypot(np.maximum(L - u, 0.0), np.abs(y - CY) * 1.25)
    return 0.004 + 0.26 * np.exp(-d / 10.0) + 0.016 * (u / L)


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def unit(v):
    n = float(np.hypot(v[0], v[1]))
    return v / n if n > 1e-9 else np.zeros(2)


def rotate(v, a):
    c, s = np.cos(a), np.sin(a)
    return np.array([c * v[0] - s * v[1], s * v[0] + c * v[1]])


def r1(v):
    return round(float(v), 1)


@dataclass
class Flight:
    kind: str                 # pass, cross, shot, clear
    team: int
    kicker: int
    start: np.ndarray
    end: np.ndarray
    t0: float
    duration: float
    height: float = 0.0
    start_z: float = 0.0
    end_z: float = 0.0
    target: int = -1          # slot that should meet the ball where it lands
    result: str = ""
    info: dict = field(default_factory=dict)


class Engine:
    def __init__(self, seed: int = 7, director: Director | None = None):
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.director = director or Director()
        self.team = np.repeat([0, 1], 11)
        self.players: list[Player] = [t.player(n) for t in TEAMS for n in t.starters]
        self.labels = [s.label for t in TEAMS for s in t.slots]
        self.depth = np.array([s.depth for t in TEAMS for s in t.slots])
        self.width = np.array([s.width for t in TEAMS for s in t.slots])
        self.gk = np.array([lab == "GK" for lab in self.labels])
        self.on_since = np.zeros(22)
        self._load_attributes()

        self.attack = np.array([1.0, -1.0])
        self.pos = np.zeros((22, 2))
        self.vel = np.zeros((22, 2))
        self.ball = np.array([L / 2, CY])
        self.ball_z = 0.0
        self.ball_v = np.zeros(2)
        self.owner = -1
        self.flight: Flight | None = None
        self.last_touch = -1
        self.poss = 0

        self.score = [0, 0]
        self.events: list[dict] = []
        self.frames: list[np.ndarray] = []
        self.periods: list[dict] = []
        self.period = 1
        self.clock = 0.0
        self.tick = 0

        self.state = KICKOFF
        self.restart: dict | None = None
        self.kickoff_team = 0
        self.kickoff_taker = 9
        self.kick_spots = np.zeros((22, 2))
        self.ready_at = 0.0
        self.goal_info: dict | None = None

        self.action: dict | None = None
        self.next_decision = 0.0
        self.runs: dict[int, tuple[np.ndarray, float]] = {}
        self.protect_until = np.zeros(22)
        self.tackle_cd = np.zeros(22)
        self.stumble_until = np.zeros(22)
        self.transition_until = [0.0, 0.0]
        self.pressure_logged = False
        self.gk_hands = False
        self.last_pass: tuple[int, int, float] | None = None
        self.pickup_block = (-1, 0.0)

    # ----------------------------------------------------------------- helpers

    def _load_attributes(self):
        p = self.players
        self.pace = np.array([x.pace for x in p])
        self.accel = np.array([4.0 if g else 4.6 + 0.8 * (x.pace - 8.6) for x, g in zip(p, self.gk)])
        self.passing = np.array([x.passing for x in p])
        self.shooting = np.array([x.shooting for x in p])
        self.dribbling = np.array([x.dribbling for x in p])
        self.tackling = np.array([x.tackling for x in p])
        self.stamina = np.array([x.stamina for x in p])

    def idx(self, team):
        return np.arange(11) + 11 * team

    def outfield(self, team):
        return np.arange(1, 11) + 11 * team

    def u_of(self, team, x):
        return x if self.attack[team] > 0 else L - x

    def x_of(self, team, u):
        return u if self.attack[team] > 0 else L - u

    def opp_goal(self, team):
        return np.array([L if self.attack[team] > 0 else 0.0, CY])

    def own_goal(self, team):
        return np.array([0.0 if self.attack[team] > 0 else L, CY])

    def tactics(self, team):
        return self.director.tactics(team, self.clock)

    def pid(self, slot):
        return self.players[slot].id if slot is not None and slot >= 0 else None

    def vmax(self):
        minutes = np.maximum(self.clock - self.on_since, 0.0) / 60.0
        v = self.pace * (1.0 - 0.07 * (minutes / 90.0) * (1.3 - self.stamina))
        return np.where(self.clock < self.stumble_until, v * 0.45, v)

    def offside_u(self, team):
        ou = np.sort(self.u_of(team, self.pos[self.idx(1 - team), 0]))[-2]
        return max(float(ou), float(self.u_of(team, self.ball[0])), L / 2)

    def in_box(self, point, team):
        """Is the point inside the penalty area that `team` attacks?"""
        return self.u_of(team, point[0]) > L - BOX_DEPTH and abs(point[1] - CY) < BOX_HALF

    def emit(self, event_type, team=None, slot=None, **extra):
        ev = {"id": len(self.events), "tick": self.tick, "period": self.period,
              "clock": r1(self.clock), "type": event_type}
        if team is not None:
            ev["team"] = int(team)
        if slot is not None and slot >= 0:
            ev["player"] = self.pid(slot)
        for k, v in extra.items():
            if isinstance(v, (np.floating, float)):
                v = r1(v)
            elif isinstance(v, np.integer):
                v = int(v)
            elif isinstance(v, np.bool_):
                v = bool(v)
            ev[k] = v
        self.events.append(ev)
        return ev

    def pick(self, values, tau):
        v = np.asarray(values, dtype=float)
        w = np.exp((v - v.max()) / tau)
        return int(self.rng.choice(len(v), p=w / w.sum()))

    # -------------------------------------------------------------- main loop

    def run(self):
        for period in (1, 2):
            self.start_period(period)
            start_tick = self.tick
            end = (45 if period == 1 else 90) * 60 + self.director.stoppage[period - 1]
            while True:
                self.step()
                if self.clock >= end and self.calm():
                    break
                if self.clock >= end + 60:
                    break
            whistle = self.emit("half_time" if period == 1 else "full_time", score=list(self.score))
            whistle["tick"] = self.tick - 1   # on the last frame of the half
            self.periods.append({"period": period, "start_tick": start_tick,
                                 "end_tick": self.tick, "start_clock": (period - 1) * 2700.0})
        return self

    def calm(self):
        if self.state == RESTART:
            return self.restart["kind"] in ("throw_in", "goal_kick")
        if self.state != PLAY:
            return False
        return 30 < self.ball[0] < 75 and (self.flight is None or self.flight.kind == "pass")

    def start_period(self, period):
        self.period = period
        self.clock = 0.0 if period == 1 else 2700.0
        if period == 2:
            self.attack = -self.attack
        self.kickoff_team = 0 if period == 1 else 1
        self.compute_kick_spots()
        self.pos[:] = self.kick_spots
        self.vel[:] = 0
        self.ball[:] = (L / 2, CY)
        self.ball_v[:] = 0
        self.ball_z = 0.0
        self.owner, self.flight, self.action = -1, None, None
        self.state = KICKOFF
        self.ready_at = self.clock + 2.0
        self.emit("period_start", score=list(self.score))

    def step(self):
        if self.state == PLAY:
            self.play()
        elif self.state == RESTART:
            self.do_restart()
        elif self.state == KICKOFF:
            self.do_kickoff()
        elif self.state == GOAL:
            self.do_celebration()
        tgt, urg = self.targets()
        self.steer(tgt, urg)
        self.update_ball()
        self.record()
        self.tick += 1
        self.clock += DT

    def record(self):
        row = np.empty(FRAME_COLS, dtype=np.float32)
        row[0] = self.period
        row[1] = self.clock
        row[2], row[3] = self.ball
        row[4] = self.ball_z
        row[5] = self.owner
        row[6] = self.state
        row[FRAME_HEAD:] = self.pos.ravel()
        self.frames.append(row)

    # ------------------------------------------------------------ on the ball

    def play(self):
        c = self.owner
        if c < 0:
            return
        team = int(self.team[c])
        opp = self.idx(1 - team)
        d = np.linalg.norm(self.pos[opp] - self.pos[c], axis=1)
        j = int(np.argmin(d))
        near, js = float(d[j]), int(opp[j])
        if near < 2.6 and not self.pressure_logged and not self.gk_hands:
            self.pressure_logged = True
            self.emit("pressure", team=1 - team, slot=js, on=self.pid(c))
        if (not self.gk_hands and near < 1.7 and self.clock >= self.protect_until[c]
                and self.clock >= self.tackle_cd[js]):
            if self.rng.random() < (0.3 + 0.5 * self.tactics(1 - team).press) * DT:
                self.tackle(js, c)
                if self.owner != c:
                    return
        if near < 2.0 and self.action and self.action["kind"] == "carry":
            self.next_decision = min(self.next_decision, self.clock + 0.25)
        if self.clock >= self.next_decision:
            self.decide(c)

    def tackle(self, t, c):
        team_c = int(self.team[c])
        p_win = float(np.clip(0.52 + 0.35 * self.tackling[t] - 0.30 * self.dribbling[c], 0.2, 0.8))
        p_foul = 0.07 + 0.07 * (1 - self.tackling[t])
        r = self.rng.random()
        if r < p_foul and not self.in_box(self.ball, team_c):
            self.emit("foul", team=1 - team_c, slot=t, on=self.pid(c),
                      x=self.ball[0], y=self.ball[1])
            if self.rng.random() < 0.14:
                self.emit("yellow_card", team=1 - team_c, slot=t)
            self.award("free_kick", team_c, self.ball.copy(), delay_ball=False)
            return
        if r < p_foul + (1 - p_foul) * p_win:
            if self.rng.random() < 0.6:
                self.emit("tackle", team=1 - team_c, slot=t, on=self.pid(c), won=True)
                self.give(t, cause="tackle")
            else:
                self.emit("tackle", team=1 - team_c, slot=t, on=self.pid(c), won=True, loose=True)
                self.loose_ball(t, self.scramble((4, 9)))
        else:
            self.emit("take_on", team=team_c, slot=c, beat=self.pid(t))
            self.protect_until[c] = self.clock + 1.0
            self.tackle_cd[t] = self.clock + 1.8
            self.stumble_until[t] = self.clock + 0.7

    def give(self, s, cause="pass"):
        team = int(self.team[s])
        self.owner = s
        self.flight = None
        self.ball_v[:] = 0
        self.ball_z = 0.0
        self.last_touch = s
        if team != self.poss:
            self.poss = team
            self.runs.clear()
            self.transition_until[team] = self.clock + 6 + 6 * self.tactics(team).counter
            self.emit("possession", team=team, slot=s, cause=cause)
        self.pressure_logged = False
        self.gk_hands = bool(self.gk[s]) and cause in ("save", "claim")
        quick = 1.25 - 0.6 * self.tactics(team).composure
        delay = self.rng.uniform(2.0, 3.5) if self.gk_hands else self.rng.uniform(0.3, 0.8) * quick
        self.next_decision = self.clock + delay
        self.action = {"kind": "hold", "target": self.pos[s].copy(), "urg": 0.0}

    def scramble(self, speed_range=(4, 9)):
        """Velocity for a ball knocked loose: random, but often towards the nearer touchline."""
        if self.rng.random() < 0.45:
            ang = (-np.pi / 2 if self.ball[1] < CY else np.pi / 2) + self.rng.normal(0, 0.5)
        else:
            ang = self.rng.uniform(0, 2 * np.pi)
        return np.array([np.cos(ang), np.sin(ang)]) * self.rng.uniform(*speed_range)

    def loose_ball(self, last, velocity):
        self.owner = -1
        self.flight = None
        self.action = None
        self.gk_hands = False
        self.ball_v = np.asarray(velocity, dtype=float)
        self.ball_z = 0.0
        if last is not None and last >= 0:
            self.last_touch = last
            self.pickup_block = (last, self.clock + 0.5)

    def pass_options(self, c, max_len=None, lofted_ok=True, backward_only=False):
        team = int(self.team[c])
        mates = np.array([s for s in self.idx(team) if s != c])
        opp = self.idx(1 - team)
        A = self.ball.copy()
        P, V = self.pos[mates], self.vel[mates]
        d0 = np.linalg.norm(P - A, axis=1)
        running = np.array([s in self.runs for s in mates])
        lead = np.where(running, 0.95, 0.35)
        B = P + V * (d0 / np.clip(9 + 0.35 * d0, 10, 22) * lead)[:, None]
        B[:, 0] = np.clip(B[:, 0], 0.5, L - 0.5)
        B[:, 1] = np.clip(B[:, 1], 0.5, W - 0.5)
        AB = B - A
        length = np.linalg.norm(AB, axis=1) + 1e-6
        lofted = (length > 34) & lofted_ok
        speed = np.where(lofted, np.clip(13 + 0.18 * length, 15, 24), np.clip(9 + 0.35 * length, 10, 23))
        T = length / speed

        O = self.pos[opp]
        t = np.clip((AB @ (O - A).T) / (length ** 2)[:, None], 0, 1)
        closest = A[None, None, :] + t[..., None] * AB[:, None, :]
        dist = np.linalg.norm(O[None] - closest, axis=2)
        ball_time = t * T[:, None] * 0.8 + 0.04
        opp_time = np.maximum(dist - 0.9, 0) / 7.5 + 0.22
        margin = opp_time - ball_time
        margin = np.where(lofted[:, None] & (t < 0.8), 5.0, margin)
        mmin = margin.min(axis=1)
        arg = margin.argmin(axis=1)
        pressure_at_target = np.linalg.norm(O[None] - B[:, None], axis=2).min(axis=1)

        calm = self.tactics(team).composure
        p = sigmoid(1.9 + 1.2 * (calm - 0.5) + 3.2 * np.clip(mmin, -1, 1.5))
        p *= 0.985 - 0.0045 * np.maximum(length - 12, 0)
        p *= 0.86 + 0.14 * self.passing[c]
        p *= 1 - (0.6 - 0.35 * calm) * np.exp(-pressure_at_target / 2.0)
        p *= np.where(lofted, 0.65, 1.0)
        p = np.clip(p, 0.02, 0.99)

        bu = self.u_of(team, A[0])
        pu = self.u_of(team, P[:, 0])
        offside = (pu > self.offside_u(team) + 0.2) & (pu > bu) & (pu > L / 2)
        valid = ~offside & (length > 4)
        if max_len is not None:
            valid &= length <= max_len
        if backward_only:
            valid &= self.u_of(team, B[:, 0]) <= bu + 1
        return {"mates": mates, "B": B, "p": p, "lofted": lofted, "speed": speed,
                "length": length, "margin": mmin, "interceptor": opp[arg],
                "icpt": closest[np.arange(len(mates)), arg], "valid": valid,
                "running": running}

    def pass_values(self, team, po, k_loss):
        bu = self.u_of(team, po["B"][:, 0])
        y = po["B"][:, 1]
        return po["p"] * threat(bu, y) - (1 - po["p"]) * k_loss * threat(L - bu, y)

    def shot_blockers(self, team):
        A = self.ball
        AG = self.opp_goal(team) - A
        opp_out = self.outfield(1 - team)
        t = np.clip(((self.pos[opp_out] - A) @ AG) / (AG @ AG), 0, 1)
        lane = np.linalg.norm(self.pos[opp_out] - (A + t[:, None] * AG), axis=1)
        width = 0.6 + 1.2 * t      # the shooting cone widens towards goal
        hit = (t > 0.04) & (t < 0.92) & (lane < width)
        return opp_out[hit], t[hit]

    def block_chance(self, team):
        return min(0.6, 0.25 * len(self.shot_blockers(team)[0]))

    def xg(self, A, team, press_d, header=False):
        g = self.opp_goal(team)
        dx = abs(g[0] - A[0])
        dy = A[1] - CY
        dist = float(np.hypot(dx, dy))
        angle = abs(np.arctan2(POST - dy, dx) - np.arctan2(-POST - dy, dx))
        z = 0.49 - 0.20 * dist + 1.0 * angle - 1.4 * np.exp(-press_d / 1.8)
        x = float(sigmoid(z)) * (0.55 if header else 1.0)
        return float(np.clip(x, 0.005, 0.8))

    def decide(self, c):
        team = int(self.team[c])
        tac = self.tactics(team)
        risk = min(1.0, tac.risk + self.director.attacking_boost(team, self.clock))
        trans = self.clock < self.transition_until[team]
        k_loss = (1.5 - 0.9 * risk) * ((1 - 0.45 * tac.counter) if trans else 1.0)
        opp = self.idx(1 - team)
        od = np.linalg.norm(self.pos[opp] - self.ball, axis=1)
        press_d = float(od.min())
        P = self.pos[c]
        bu = float(self.u_of(team, self.ball[0]))
        by = float(self.ball[1])

        vals, acts = [], []
        po = self.pass_options(c)
        pv = self.pass_values(team, po, k_loss)
        if trans:
            gain = self.u_of(team, po["B"][:, 0]) - bu
            pv = pv + 0.014 * tac.counter * np.clip(gain / 25, 0, 1)
        for i in np.flatnonzero(po["valid"]):
            vals.append(pv[i])
            acts.append(("pass", int(i)))

        if self.gk[c]:
            vals.append(0.004)
            acts.append(("clear", None))
        else:
            dist_goal = float(np.linalg.norm(self.opp_goal(team) - self.ball))
            if dist_goal < 24:
                xg = self.xg(self.ball, team, press_d) * (1 - 0.5 * self.block_chance(team))
                vals.append(xg * (0.32 + 0.2 * risk))
                acts.append(("shot", xg))

            tgt, val = self.carry_option(c, k_loss)
            vals.append(val)
            acts.append(("carry", tgt))

            p_hold = 1 - 0.75 * np.exp(-press_d / 1.6)
            vals.append(p_hold * threat(bu, by) - (1 - p_hold) * k_loss * threat(L - bu, by))
            nearest = self.pos[opp[int(np.argmin(od))]]
            acts.append(("hold", P + unit(P - nearest) * 1.5))

            if bu > 70 and abs(by - CY) > 13:
                cross = self.cross_option(c, k_loss)
                if cross is not None:
                    vals.append(cross[0])
                    acts.append(("cross", cross[1]))

            if bu < 30 and press_d < 4:
                land_u = min(bu + 45, 100)
                vals.append(0.5 * threat(land_u, CY) - 0.5 * k_loss * threat(L - land_u, CY))
                acts.append(("clear", None))

        if not vals:
            self.next_decision = self.clock + 0.3
            return
        kind, data = acts[self.pick(vals, 0.003)]
        if kind == "pass":
            self.kick_pass(c, po, data)
        elif kind == "shot":
            self.shoot(c)
        elif kind == "carry":
            until = self.clock + self.rng.uniform(0.7, 1.4)
            self.action = {"kind": "carry", "target": data, "urg": 0.72 + 0.08 * self.dribbling[c]}
            self.next_decision = until
        elif kind == "hold":
            self.action = {"kind": "hold", "target": data, "urg": 0.25}
            self.next_decision = self.clock + self.rng.uniform(0.35, 0.8)
        elif kind == "cross":
            self.kick_cross(c, data)
        elif kind == "clear":
            self.kick_clear(c)

    def carry_option(self, c, k_loss):
        team = int(self.team[c])
        P = self.pos[c]
        fwd = unit(self.opp_goal(team) - P)
        O = self.pos[self.idx(1 - team)]
        best_t, best_v = P.copy(), -1.0
        for a in (-0.9, -0.45, 0.0, 0.45, 0.9):
            tgt = P + rotate(fwd, a) * 7
            tgt = np.array([np.clip(tgt[0], 1, L - 1), np.clip(tgt[1], 1, W - 1)])
            seg = tgt - P
            t = np.clip(((O - P) @ seg) / max(seg @ seg, 1e-6), 0.15, 1.0)
            space = float(np.min(np.linalg.norm(O - (P + t[:, None] * seg), axis=1)))
            p_keep = 1 - 0.95 * np.exp(-space / (1.4 + 1.8 * self.dribbling[c]))
            u = self.u_of(team, tgt[0])
            val = p_keep * threat(u, tgt[1]) - (1 - p_keep) * k_loss * threat(L - u, tgt[1]) + 0.0005
            if val > best_v:
                best_t, best_v = tgt, float(val)
        return best_t, best_v

    def cross_option(self, c, k_loss):
        team = int(self.team[c])
        mates = [s for s in self.outfield(team) if s != c]
        box = [s for s in mates if self.u_of(team, self.pos[s, 0]) > L - 19
               and abs(self.pos[s, 1] - CY) < 13]
        if not box:
            return None
        defenders = self.outfield(1 - team)
        n_def = sum(1 for s in defenders if self.in_box(self.pos[s], team))
        O = self.pos[defenders]
        att = max(box, key=lambda s: float(np.min(np.linalg.norm(O - self.pos[s], axis=1))))
        landing = self.pos[att] + self.vel[att] * 0.8
        landing[1] = np.clip(landing[1], CY - 12, CY + 12)
        lu = np.clip(self.u_of(team, landing[0]), L - 16, L - 4)
        landing[0] = self.x_of(team, lu)
        p_win = float(np.clip(0.40 + 0.06 * len(box) - 0.05 * n_def, 0.12, 0.5))
        head_xg = self.xg(landing, team, 2.0, header=True)
        val = p_win * head_xg * 1.4 - (1 - p_win) * k_loss * 0.3 * threat(L - lu, landing[1])
        return val, (att, landing, p_win)

    # ------------------------------------------------------------------ kicks

    def kick_pass(self, c, po, i):
        team = int(self.team[c])
        A = self.ball.copy()
        p = float(po["p"][i])
        target_point = po["B"][i]
        receiver = int(po["mates"][i])
        if self.rng.random() < p:
            end, who, result = target_point.copy(), receiver, "complete"
        elif po["margin"][i] < 0.9 and self.rng.random() < 0.65:
            end, who, result = po["icpt"][i].copy(), int(po["interceptor"][i]), "intercepted"
        else:
            d = unit(target_point - A)
            end = target_point + d * self.rng.uniform(2, 10) + self.rng.normal(0, 5, 2)
            who, result = -1, "misplaced"
        speed = float(po["speed"][i])
        lofted = bool(po["lofted"][i])
        dist = float(np.linalg.norm(end - A))
        info = {"receiver": receiver, "length": float(po["length"][i]), "lofted": lofted,
                "difficulty": int(round(100 * (1 - p))), "through": bool(po["running"][i]),
                "speed": speed, "progress": float(self.u_of(team, target_point[0]) - self.u_of(team, A[0])),
                "start_tick": self.tick}
        self.flight = Flight("pass", team, c, A, end, self.clock, max(dist / speed, 0.15),
                             height=float(np.clip(0.1 * dist, 2.5, 11)) if lofted else 0.0,
                             target=who, result=result, info=info)
        self.release(c)

    def release(self, c):
        self.owner = -1
        self.last_touch = c
        self.action = None
        self.gk_hands = False
        self.ball_v[:] = 0

    def shoot(self, c, kind="open"):
        team = int(self.team[c])
        A = self.ball.copy()
        g = self.opp_goal(team)
        press_d = float(np.min(np.linalg.norm(self.pos[self.idx(1 - team)] - A, axis=1)))
        header = kind == "header"
        xg = self.xg(A, team, press_d, header=header)
        if kind == "free_kick":
            xg *= 0.7
        dist = float(np.linalg.norm(g - A))
        fin = self.director.finishing(team, self.clock)
        p_goal = min(0.85, xg * (0.7 + 0.6 * self.shooting[c]) * fin)

        AG = g - A
        blockers, block_t = self.shot_blockers(team)
        p_block = 0.0 if header or kind == "free_kick" else self.block_chance(team)

        gk = int(self.idx(1 - team)[0])
        side = self.rng.choice([-1.0, 1.0])
        if self.rng.random() < p_block:
            result = "blocked"
        else:
            r = self.rng.random()
            if r < p_goal:
                result = "goal"
            elif r < p_goal + (1 - p_goal) * (0.30 + 0.25 * self.shooting[c]):
                result = "saved"
            else:
                result = "off_target"

        if header:
            kmh = self.rng.uniform(38, 62)
        elif kind == "free_kick":
            kmh = self.rng.normal(95, 6)
        else:
            kmh = float(np.clip(self.rng.normal(84 + 26 * self.shooting[c] - 0.45 * dist, 7), 48, 128))
        v = kmh / 3.6
        into = self.attack[team]
        target = -1
        end_z = 0.0
        gk_point = self.pos[gk].copy()

        if result == "goal":
            gy = CY + side * self.rng.uniform(0.6, 3.3)
            end_z = float(self.rng.uniform(0.15, 2.2))
            end = np.array([g[0] + into * 1.0, gy])
            frac = np.clip((abs(self.pos[gk, 0] - A[0])) / max(abs(g[0] - A[0]), 1), 0.4, 1)
            gk_point = A + (np.array([g[0], gy]) - A) * frac + np.array([0, -side * 0.8])
        elif result == "saved":
            gy = CY + self.rng.uniform(-2.8, 2.8)
            frac = np.clip((abs(self.pos[gk, 0] - A[0])) / max(abs(g[0] - A[0]), 1), 0.5, 1)
            end = A + (np.array([g[0], gy]) - A) * frac
            end_z = float(self.rng.uniform(0.2, 1.8))
            gk_point = end.copy()
            target = gk
        elif result == "off_target":
            if self.rng.random() < 0.35:
                gy = CY + self.rng.uniform(-3.4, 3.4)
                end_z = float(self.rng.uniform(2.7, 4.5))
            else:
                gy = CY + side * self.rng.uniform(4.0, 8.0)
                end_z = float(self.rng.uniform(0.2, 2.0))
            end = np.array([g[0] + into * 2.5, gy])
            gk_point = A + (np.array([g[0], CY]) - A) * 0.9
        else:
            k = int(np.argmin(block_t))
            target = int(blockers[k])
            end = A + AG * float(block_t[k])

        self.flight = Flight("shot", team, c, A, end, self.clock,
                             max(float(np.linalg.norm(end - A)) / v, 0.1),
                             height=0.4 if result != "blocked" else 0.0,
                             start_z=1.8 if header else 0.1, end_z=end_z, target=target,
                             result=result,
                             info={"xg": round(xg, 3), "speed_kmh": round(kmh), "shot_type": kind,
                                   "distance": dist, "gk_point": gk_point, "x": A[0], "y": A[1],
                                   "blocker": target if result == "blocked" else -1})
        self.release(c)

    def kick_cross(self, c, data):
        att, landing, p_win = data
        team = int(self.team[c])
        A = self.ball.copy()
        dist = float(np.linalg.norm(landing - A))
        won = self.rng.random() < p_win
        self.flight = Flight("cross", team, c, A, landing.copy(), self.clock, max(dist / 20.0, 0.4),
                             height=float(np.clip(0.12 * dist, 3, 8)), end_z=1.8, target=att,
                             result="won" if won else "lost",
                             info={"length": dist, "p_win": p_win})
        self.release(c)

    def kick_clear(self, c):
        team = int(self.team[c])
        A = self.ball.copy()
        u = min(self.u_of(team, A[0]) + self.rng.uniform(35, 55), 100)
        end = np.array([self.x_of(team, u), np.clip(A[1] + self.rng.normal(0, 18), -4, W + 4)])
        dist = float(np.linalg.norm(end - A))
        self.emit("clearance", team=team, slot=c, x=A[0], y=A[1])
        self.flight = Flight("clear", team, c, A, end, self.clock, dist / self.rng.uniform(20, 26),
                             height=float(np.clip(0.12 * dist, 6, 16)), info={"length": dist})
        self.release(c)

    # --------------------------------------------------------- ball movement

    def update_ball(self):
        if self.owner >= 0:
            s = self.owner
            v = self.vel[s]
            sp = float(np.hypot(v[0], v[1]))
            face = v / sp if sp > 0.6 else unit(self.opp_goal(self.team[s]) - self.pos[s])
            if self.gk_hands:
                self.ball = self.pos[s] + face * 0.25
                self.ball_z = 1.0
            else:
                self.ball = self.pos[s] + face * 0.55
                self.ball_z = 0.0
            return
        if self.flight is not None:
            self.advance_flight()
            return
        sp = float(np.hypot(*self.ball_v))
        if sp > 0:
            self.ball_v -= self.ball_v / sp * min(sp, 2.2 * DT)
        self.ball = self.ball + self.ball_v * DT
        self.ball_z = 0.0
        if self.state != PLAY:
            return
        if self.out_of_play():
            return
        self.try_pickup()

    def advance_flight(self):
        f = self.flight
        p = (self.clock + DT - f.t0) / f.duration
        if p >= 1:
            self.ball = f.end.copy()
            self.ball_z = f.end_z
            self.arrive()
            return
        s = p if f.kind == "shot" else 0.6 * p * (2 - p) + 0.4 * p
        self.ball = f.start + (f.end - f.start) * s
        self.ball_z = 4 * f.height * p * (1 - p) + f.start_z * (1 - p) + f.end_z * p
        if not (f.kind == "shot" and f.result == "goal"):
            self.out_of_play()

    def arrive(self):
        f = self.flight
        self.flight = None
        if f.kind == "shot":
            self.shot_arrival(f)
        elif f.kind == "cross":
            self.cross_arrival(f)
        elif f.kind == "pass":
            r = f.target
            base = {"x": f.start[0], "y": f.start[1], "end_x": self.ball[0], "end_y": self.ball[1],
                    "length": f.info["length"], "difficulty": f.info["difficulty"],
                    "lofted": f.info["lofted"], "through": f.info["through"],
                    "speed_kmh": round(f.info["speed"] * 3.6), "progress": f.info["progress"],
                    "start_tick": f.info["start_tick"]}
            if r >= 0 and np.linalg.norm(self.pos[r] - self.ball) < 2.5:
                same = self.team[r] == f.team
                self.emit("pass", team=f.team, slot=f.kicker, to=self.pid(r) if same else None,
                          outcome="complete" if same else "intercepted", **base)
                if same:
                    self.last_pass = (f.kicker, r, self.clock)
                else:
                    self.emit("interception", team=int(self.team[r]), slot=r)
                    if self.rng.random() < 0.3:
                        self.loose_ball(r, self.scramble((4, 10)))
                        return
                self.give(r, cause="pass" if same else "interception")
                return
            self.emit("pass", team=f.team, slot=f.kicker, to=None, outcome="incomplete", **base)
            residual = unit(f.end - f.start) * f.info["speed"] * (0.2 if f.info["lofted"] else 0.35)
            self.loose_ball(f.kicker, residual)
        else:
            self.loose_ball(f.kicker, unit(f.end - f.start) * 5.0)

    def shot_arrival(self, f):
        team, shooter = f.team, f.kicker
        info = {k: f.info[k] for k in ("xg", "speed_kmh", "shot_type", "distance", "x", "y")}
        if f.result == "goal":
            self.score[team] += 1
            self.director.record_goal(team, self.clock)
            assist = None
            if self.last_pass and self.last_pass[1] == shooter and self.clock - self.last_pass[2] < 12:
                assist = self.pid(self.last_pass[0])
            self.emit("shot", team=team, slot=shooter, outcome="goal", **info)
            self.emit("goal", team=team, slot=shooter, assist=assist, score=list(self.score), **info)
            self.owner = -1
            self.ball_v[:] = 0
            g = self.opp_goal(team)
            flag = np.array([g[0] - self.attack[team] * 1.0, 1.0 if self.pos[shooter, 1] < CY else W - 1.0])
            self.state = GOAL
            self.goal_info = {"scorer": shooter, "team": team, "t0": self.clock, "flag": flag}
            self.runs.clear()
            self.kickoff_team = 1 - team
            self.compute_kick_spots()
            return
        if f.result == "saved":
            gk = f.target
            self.emit("shot", team=team, slot=shooter, outcome="saved", **info)
            self.emit("save", team=1 - team, slot=gk, xg=info["xg"], speed_kmh=info["speed_kmh"])
            self.last_touch = gk
            r = self.rng.random()
            if r < 0.5:
                self.give(gk, cause="save")
            elif r < 0.72:
                self.emit("corner_conceded", team=1 - team, slot=gk)
                self.award("corner", team, np.array([self.opp_goal(team)[0], 0.0 if f.end[1] < CY else W]))
            else:
                away = unit(f.end - f.start)
                side = rotate(away, self.rng.choice([-1, 1]) * self.rng.uniform(0.9, 1.8))
                self.loose_ball(gk, side * self.rng.uniform(5, 10))
            return
        if f.result == "blocked":
            b = f.target
            self.emit("shot", team=team, slot=shooter, outcome="blocked", **info)
            self.emit("block", team=1 - team, slot=b)
            if self.rng.random() < 0.35:
                self.last_touch = b
                self.award("corner", team, np.array([self.opp_goal(team)[0], 0.0 if self.ball[1] < CY else W]))
                return
            back = -unit(f.end - f.start)
            self.loose_ball(b, rotate(back, self.rng.uniform(-1.2, 1.2)) * self.rng.uniform(4, 9))
            return
        # an off-target shot that somehow stopped short of the line
        self.emit("shot", team=team, slot=shooter, outcome="off_target", **info)
        self.loose_ball(shooter, unit(f.end - f.start) * 4)

    def cross_arrival(self, f):
        att = f.target
        team = f.team
        if f.result == "won" and np.linalg.norm(self.pos[att] - self.ball) < 3.0:
            self.emit("cross", team=team, slot=f.kicker, to=self.pid(att), outcome="complete",
                      x=f.start[0], y=f.start[1], end_x=self.ball[0], end_y=self.ball[1])
            self.last_pass = (f.kicker, att, self.clock)
            self.last_touch = att
            self.shoot(att, kind="header")
            return
        defenders = self.outfield(1 - team)
        d = defenders[int(np.argmin(np.linalg.norm(self.pos[defenders] - self.ball, axis=1)))]
        self.emit("cross", team=team, slot=f.kicker, to=None, outcome="cleared",
                  x=f.start[0], y=f.start[1], end_x=self.ball[0], end_y=self.ball[1])
        if self.rng.random() < 0.3:
            self.emit("clearance", team=1 - team, slot=int(d), x=self.ball[0], y=self.ball[1])
            g = self.opp_goal(team)
            self.last_touch = int(d)
            self.award("corner", team, np.array([g[0], 0.0 if self.ball[1] < CY else W]))
            return
        self.kick_clear(int(d))

    def try_pickup(self):
        d = np.linalg.norm(self.pos - self.ball, axis=1)
        reach = np.full(22, 1.0)
        for team in (0, 1):
            g = int(self.idx(team)[0])
            if self.in_box(self.ball, 1 - team):
                reach[g] = 1.8
        blocked, until = self.pickup_block
        if blocked >= 0 and self.clock < until:
            d[blocked] = 99
        cand = np.flatnonzero(d < reach)
        if len(cand) == 0:
            return
        if len(cand) > 1:
            w = 1.0 / (d[cand] + 0.2)
            s = int(self.rng.choice(cand, p=w / w.sum()))
        else:
            s = int(cand[0])
        team = int(self.team[s])
        claim = bool(self.gk[s]) and reach[s] > 1.0
        if team != self.poss:
            self.emit("recovery", team=team, slot=s, x=self.ball[0], y=self.ball[1])
        self.give(s, cause="claim" if claim else "recovery")

    def out_of_play(self):
        x, y = self.ball
        if 0 <= x <= L and 0 <= y <= W:
            return False
        f = self.flight
        if f is not None and f.kind == "shot":
            info = {k: f.info[k] for k in ("xg", "speed_kmh", "shot_type", "distance", "x", "y")}
            self.emit("shot", team=f.team, slot=f.kicker, outcome="off_target", **info)
        if f is not None and f.kind == "pass":
            self.emit("pass", team=f.team, slot=f.kicker, to=None, outcome="out",
                      x=f.start[0], y=f.start[1], end_x=x, end_y=y, length=f.info["length"],
                      difficulty=f.info["difficulty"], lofted=f.info["lofted"],
                      through=f.info["through"], speed_kmh=round(f.info["speed"] * 3.6),
                      progress=f.info["progress"])
        lt = self.last_touch
        lt_team = int(self.team[lt]) if lt >= 0 else self.poss
        self.flight = None
        self.owner = -1
        self.ball_v[:] = 0
        if 0 <= x <= L:
            self.award("throw_in", 1 - lt_team, np.array([np.clip(x, 0.5, L - 0.5), 0.0 if y < 0 else W]))
            return True
        attacking = 0 if (x > L) == (self.attack[0] > 0) else 1
        defending = 1 - attacking
        if lt_team == attacking:
            spot = np.array([self.x_of(defending, 5.5), CY + (6.0 if y > CY else -6.0)])
            self.award("goal_kick", defending, spot)
        else:
            spot = np.array([0.0 if x < 0 else L, 0.0 if y < CY else W])
            self.award("corner", attacking, spot)
        return True

    # -------------------------------------------------------------- restarts

    def award(self, kind, team, spot, delay_ball=True):
        self.apply_due_subs()
        self.state = RESTART
        self.owner = -1
        self.flight = None
        self.action = None
        self.gk_hands = False
        self.runs.clear()
        if kind == "goal_kick":
            taker = int(self.idx(team)[0])
        else:
            cand = self.outfield(team)
            taker = int(cand[np.argmin(np.linalg.norm(self.pos[cand] - spot, axis=1))])
        delay = {"throw_in": (6, 12), "goal_kick": (12, 22), "corner": (18, 30),
                 "free_kick": (15, 28)}[kind]
        self.restart = {"kind": kind, "team": team, "spot": spot, "taker": taker,
                        "ready_at": self.clock + self.rng.uniform(*delay),
                        "ball_at": self.clock + (1.2 if delay_ball else 0.0)}
        if kind == "corner":
            self.restart["box"] = self.corner_spots(team)
        self.poss = team
        self.emit(kind, team=team, x=spot[0], y=spot[1])

    def corner_spots(self, team):
        spots = {}
        att = [s for s in self.outfield(team) if self.labels[s] not in ("RB", "LB", "DM", "RDM", "LDM")]
        for s in att:
            u = self.rng.uniform(L - 14, L - 4)
            spots[int(s)] = np.array([self.x_of(team, u), CY + self.rng.uniform(-9, 9)])
        for s in self.outfield(1 - team):
            u = self.rng.uniform(1.5, 13)
            spots[int(s)] = np.array([self.x_of(1 - team, u), CY + self.rng.uniform(-10, 10)])
        return spots

    def do_restart(self):
        r = self.restart
        spot = r["spot"]
        if self.clock >= r["ball_at"]:
            self.ball = spot.copy()
            self.ball_z = 0.0
            self.ball_v[:] = 0
        taker = r["taker"]
        if self.clock < r["ready_at"] or np.linalg.norm(self.pos[taker] - spot) > 1.0:
            return
        kind, team = r["kind"], r["team"]
        self.restart = None
        self.state = PLAY
        self.ball = spot.copy()
        self.owner = taker
        self.last_touch = taker
        self.poss = team
        self.pressure_logged = False
        self.gk_hands = False
        if kind == "corner" and self.rng.random() > 0.15:
            cross = self.cross_option(taker, 1.0)
            if cross is not None:
                self.kick_cross(taker, cross[1])
                return
        if kind == "free_kick":
            g = self.opp_goal(team)
            if np.linalg.norm(g - spot) < 28 and abs(spot[1] - CY) < 16 and self.rng.random() < 0.5:
                self.shoot(taker, kind="free_kick")
                return
        max_len = 28 if kind == "throw_in" else None
        po = self.pass_options(taker, max_len=max_len, lofted_ok=kind != "throw_in")
        if kind == "goal_kick" and self.rng.random() < 0.45:
            po["valid"] &= po["lofted"]
        valid = np.flatnonzero(po["valid"])
        if len(valid) == 0:
            po = self.pass_options(taker, lofted_ok=kind != "throw_in")
            valid = np.flatnonzero(po["valid"])
        if len(valid) == 0:
            self.next_decision = self.clock + 0.5
            return
        vals = self.pass_values(team, po, 1.2)[valid]
        self.kick_pass(taker, po, int(valid[self.pick(vals, 0.003)]))

    def compute_kick_spots(self):
        spots = np.empty((22, 2))
        kt = self.kickoff_team
        for team in (0, 1):
            idx = self.idx(team)
            u = np.where(self.gk[idx], 4.0, 16 + self.depth[idx] * 28)
            u = np.minimum(u, 50.5 if team == kt else 42.5)
            y = CY + self.attack[team] * (0.5 - self.width[idx]) * 52
            spots[idx, 0] = self.x_of(team, u)
            spots[idx, 1] = y
        idx = self.idx(kt)
        labels = [self.labels[i] for i in idx]
        taker = int(idx[labels.index("ST")])
        spots[taker] = (L / 2 - self.attack[kt] * 0.4, CY)
        second = next(int(idx[labels.index(lab)]) for lab in ("CAM", "LCM") if lab in labels)
        spots[second] = (self.x_of(kt, 49.0), CY + 6)
        self.kickoff_taker = taker
        self.kick_spots = spots

    def do_kickoff(self):
        if self.clock < self.ready_at:
            return
        t = self.kickoff_taker
        settled = np.max(np.linalg.norm(self.pos - self.kick_spots, axis=1)) < 4
        if np.linalg.norm(self.pos[t] - self.kick_spots[t]) > 1.5:
            return
        if not settled and self.clock < self.ready_at + 15:
            return
        self.state = PLAY
        self.ball[:] = (L / 2, CY)
        self.owner = t
        self.last_touch = t
        self.poss = self.kickoff_team
        self.emit("kick_off", team=self.kickoff_team, slot=t)
        po = self.pass_options(t, max_len=30, lofted_ok=False, backward_only=True)
        valid = np.flatnonzero(po["valid"])
        if len(valid):
            vals = self.pass_values(self.kickoff_team, po, 1.2)[valid]
            self.kick_pass(t, po, int(valid[self.pick(vals, 0.003)]))
        else:
            self.next_decision = self.clock + 0.3

    def do_celebration(self):
        if self.clock < self.goal_info["t0"] + 28:
            return
        self.apply_due_subs()
        self.ball[:] = (L / 2, CY)
        self.ball_z = 0.0
        self.state = KICKOFF
        self.ready_at = self.clock + 8

    def apply_due_subs(self):
        for sub in self.director.due_subs(self.clock):
            team = TEAMS[sub.team]
            slot = next(int(i) for i in self.idx(sub.team) if self.players[i].number == sub.off_number)
            old = self.players[slot]
            new = team.player(sub.on_number)
            self.players[slot] = new
            self.on_since[slot] = self.clock
            self._load_attributes()
            self.pos[slot] = (L / 2 + self.rng.uniform(-3, 3), -0.8)
            self.vel[slot] = 0
            self.runs.pop(slot, None)
            self.emit("substitution", team=sub.team, slot=slot, off=old.id, on=new.id,
                      slot_index=slot)

    # ------------------------------------------------------------- movement

    def shape(self, team, in_poss, ball=None):
        b = self.ball if ball is None else ball
        tac = self.tactics(team)
        idx = self.idx(team)
        bu = self.u_of(team, b[0])
        by = b[1]
        d = self.depth[idx].copy()
        w = self.width[idx]
        labels = [self.labels[i] for i in idx]
        if in_poss:
            back = np.clip(bu - 36 + 10 * tac.line, 12, 56)
            length = 32 + 10 * tac.risk
            width = 58.0
            cy = CY + (by - CY) * 0.15
            for k, lab in enumerate(labels):
                if lab in ("RB", "LB"):
                    d[k] += 0.2 + 0.25 * tac.risk
        else:
            back = np.clip(bu - 30 + 16 * tac.line, 7, 42)
            length = 22 + 8 * tac.line
            near_goal = float(np.clip((40 - bu) / 25, 0, 1))
            width = 40.0 - 12 * near_goal
            cy = CY + (by - CY) * (0.45 + 0.1 * near_goal)
            for k, lab in enumerate(labels):
                if lab in ("RW", "LW", "RAM", "LAM"):
                    d[k] -= 0.15
        u = back + d * length
        y = cy + self.attack[team] * (0.5 - w) * width
        if not in_poss and tac.counter > 0.3:
            # counter-attacking sides leave outlets up the pitch
            outlet = min(36 + 18 * tac.counter, self.offside_u(team) - 1.0)
            for k, lab in enumerate(labels):
                if lab == "ST" or (tac.counter > 0.7 and lab in ("RW", "LW", "RAM", "LAM")):
                    u[k] = max(u[k], outlet - (0 if lab == "ST" else 6))
        if in_poss:
            u = np.minimum(u, self.offside_u(team) - 0.8)
        u = np.clip(u, 2, L - 2)
        y = np.clip(y, 1.5, W - 1.5)
        out = np.column_stack([self.x_of(team, u), y])
        out[0] = self.gk_spot(team, in_poss, b)
        return out

    def gk_spot(self, team, in_poss, b):
        bu = self.u_of(team, b[0])
        if in_poss:
            u = np.clip(3 + 0.16 * bu, 3, 22)
        else:
            u = np.clip(1.2 + 0.09 * bu, 1.2, 10)
        y = CY + (b[1] - CY) * (0.25 if bu < 35 else 0.1)
        return np.array([self.x_of(team, u), y])

    def mark(self, team, tgt, skip=(), exclude=(), urg=None):
        idx = [int(s) for s in self.outfield(team) if s not in skip]
        att = [int(s) for s in self.outfield(1 - team) if s not in exclude]
        if not idx or not att:
            return
        anchors = tgt[idx]
        D = np.linalg.norm(anchors[:, None] - self.pos[att][None], axis=2)
        g = self.own_goal(team)
        ball_u = self.u_of(team, self.ball[0])
        taken_d, taken_a = set(), set()
        for flat in np.argsort(D, axis=None):
            i, j = divmod(int(flat), len(att))
            if i in taken_d or j in taken_a:
                continue
            if D[i, j] > 16:
                break
            taken_d.add(i)
            taken_a.add(j)
            a = self.pos[att[j]]
            danger = L - self.u_of(1 - team, a[0])   # attacker's distance from our goal line
            if danger < 20:
                m, gap = 0.92, 1.2
            elif ball_u < 40:
                m, gap = 0.6, 1.8
            else:
                m, gap = 0.3, 2.0
            goalside = a + unit(g - a) * gap
            tgt[idx[i]] = anchors[i] + m * (goalside - anchors[i])
            if urg is not None:
                running = np.hypot(*self.vel[att[j]]) > 5.0
                if danger < 30 or (running and danger < 50):
                    urg[idx[i]] = max(urg[idx[i]], 0.92 if running else 0.6)

    def update_runs(self, team, c):
        for s in list(self.runs):
            if self.runs[s][1] < self.clock or self.team[s] != team:
                del self.runs[s]
        bu = self.u_of(team, self.ball[0])
        if bu < 35:
            return
        tac = self.tactics(team)
        risk = min(1.0, tac.risk + self.director.attacking_boost(team, self.clock))
        trans = self.clock < self.transition_until[team]
        rate = 0.02 + 0.06 * risk + (0.12 * tac.counter if trans else 0.0)
        ou = self.offside_u(team)
        for s in self.outfield(team):
            s = int(s)
            if s == c or s in self.runs:
                continue
            weight = RUN_WEIGHT.get(self.labels[s], 0.0)
            if self.labels[s] in ("RB", "LB") and bu < 55:
                weight = 0.0
            if weight and self.rng.random() < rate * weight * DT:
                u = min(ou + self.rng.uniform(4, 14), L - 5)
                y0 = self.pos[s, 1]
                y = np.clip(y0 + (CY - y0) * self.rng.uniform(0.1, 0.5) + self.rng.normal(0, 4), 4, W - 4)
                self.runs[s] = (np.array([self.x_of(team, u), y]), self.clock + self.rng.uniform(2.0, 3.5))

    def targets(self):
        tgt = np.empty((22, 2))
        urg = np.zeros(22)
        if self.state == PLAY:
            self.targets_play(tgt, urg)
        elif self.state == RESTART:
            self.targets_restart(tgt, urg)
        elif self.state == KICKOFF:
            tgt[:] = self.kick_spots
            urg[self.kickoff_taker] = 0.4
        else:
            self.targets_goal(tgt, urg)
        tgt[:, 0] = np.clip(tgt[:, 0], -2, L + 2)
        tgt[:, 1] = np.clip(tgt[:, 1], -2, W + 2)
        return tgt, urg

    def targets_play(self, tgt, urg):
        for team in (0, 1):
            tgt[self.idx(team)] = self.shape(team, team == self.poss)
        c, f = self.owner, self.flight
        if c >= 0:
            team = int(self.team[c])
            self.update_runs(team, c)
            self.support(team, c, tgt, urg)
            if self.gk_hands:
                self.mark(1 - team, tgt)
            else:
                self.defend(1 - team, c, tgt, urg)
            if not self.gk_hands:
                self.recover(1 - team, urg)
            if self.action:
                tgt[c] = self.action["target"]
                urg[c] = self.action.get("urg", 0.0)
            else:
                tgt[c] = self.pos[c]
        elif f is not None:
            self.mark(1 - f.team, tgt, urg=urg)
            if f.kind == "shot":
                gk = int(self.idx(1 - f.team)[0])
                tgt[gk] = f.info["gk_point"]
                urg[gk] = 1.0
            else:
                if f.target >= 0:
                    tgt[f.target] = f.end
                    urg[f.target] = 1.0
                receiver = f.info.get("receiver", -1)
                if receiver is not None and receiver >= 0 and receiver != f.target:
                    tgt[receiver] = f.end
                    urg[receiver] = 0.9
                if f.kind in ("clear", "cross") or f.result == "misplaced":
                    for team in (0, 1):
                        cand = self.outfield(team)
                        s = int(cand[np.argmin(np.linalg.norm(self.pos[cand] - f.end, axis=1))])
                        if s != f.target:
                            tgt[s] = f.end
                            urg[s] = 0.9
            for s, (t, _) in self.runs.items():
                if s != f.target:
                    tgt[s] = t
                    urg[s] = 0.95
        else:
            pred = self.ball + self.ball_v * 0.6
            for team in (0, 1):
                cand = self.outfield(team)
                if self.in_box(self.ball, 1 - team):
                    cand = self.idx(team)
                d = np.linalg.norm(self.pos[cand] - pred, axis=1) / self.pace[cand]
                order = cand[np.argsort(d)]
                tgt[order[0]] = pred
                urg[order[0]] = 1.0
                tgt[order[1]] = pred
                urg[order[1]] = 0.55

    def recover(self, team, urg):
        """Players caught on the wrong side of the ball get back at speed."""
        idx = self.outfield(team)
        bu = self.u_of(team, self.ball[0])
        behind = self.u_of(team, self.pos[idx, 0]) > bu + 3
        urg[idx] = np.where(behind, np.maximum(urg[idx], 0.8), urg[idx])

    def support(self, team, c, tgt, urg):
        for s, (t, _) in self.runs.items():
            tgt[s] = t
            urg[s] = 0.95
        cand = [int(s) for s in self.outfield(team) if s != c and s not in self.runs]
        cand.sort(key=lambda s: float(np.linalg.norm(self.pos[s] - self.pos[c])))
        for s in cand[:2]:
            a = tgt[s]
            t = a + 0.35 * (self.pos[c] - a)
            off = t - self.pos[c]
            if np.hypot(*off) < 10:
                t = self.pos[c] + (unit(off) if np.hypot(*off) > 0.1 else np.array([0, 1.0])) * 10
            tgt[s] = t

    def defend(self, team, c, tgt, urg):
        tac = self.tactics(team)
        idx = self.outfield(team)
        cpos = self.pos[c]
        d = np.linalg.norm(self.pos[idx] - cpos, axis=1)
        order = idx[np.argsort(d)]
        cu = self.u_of(team, cpos[0])
        pressing = cu < 30 + 60 * tac.press or d.min() < 5
        danger = cu < 35
        first = int(order[0])
        if pressing:
            g = self.own_goal(team)
            tgt[first] = cpos + self.vel[c] * 0.35 + unit(g - cpos) * 1.2
            urg[first] = 0.65 + 0.35 * tac.press
        else:
            tgt[first] = cpos + unit(self.own_goal(team) - cpos) * 6
        if danger:
            second = int(order[1])
            g = self.own_goal(team)
            tgt[second] = cpos + unit(g - cpos) * min(4.0, np.linalg.norm(g - cpos) * 0.4)
            urg[second] = 0.85
            self.mark(team, tgt, skip={first, second}, exclude={c}, urg=urg)
        elif pressing and tac.press > 0.55:
            self.mark(team, tgt, skip={first}, exclude={c}, urg=urg)
            second = int(order[1])
            att = np.array([s for s in self.outfield(1 - team) if s != c])
            k = att[int(np.argmin(np.linalg.norm(self.pos[att] - cpos, axis=1)))]
            tgt[second] = cpos + 0.55 * (self.pos[k] - cpos)
            urg[second] = 0.5 + 0.3 * tac.press
        else:
            self.mark(team, tgt, skip={first}, exclude={c}, urg=urg)

    def targets_restart(self, tgt, urg):
        r = self.restart
        team, spot, kind = r["team"], r["spot"], r["kind"]
        for t in (0, 1):
            tgt[self.idx(t)] = self.shape(t, t == team, ball=spot)
        if kind == "corner":
            for s, p in r["box"].items():
                tgt[s] = p
        if kind in ("free_kick", "corner"):
            for s in self.idx(1 - team):
                off = tgt[s] - spot
                dist = np.hypot(*off)
                if dist < 9.2:
                    tgt[s] = spot + (unit(off) if dist > 0.1 else unit(self.own_goal(1 - team) - spot)) * 9.4
        if kind == "goal_kick":
            for s in self.outfield(1 - team):
                u = self.u_of(team, tgt[s, 0])
                if u < 18:
                    tgt[s, 0] = self.x_of(team, 18.5)
        tgt[r["taker"]] = spot
        urg[r["taker"]] = 0.55

    def targets_goal(self, tgt, urg):
        g = self.goal_info
        tgt[:] = self.kick_spots
        scorer, team = g["scorer"], g["team"]
        since = self.clock - g["t0"]
        if since < 9:
            tgt[scorer] = g["flag"]
            urg[scorer] = 0.85
            for s in self.outfield(team):
                if s != scorer and np.linalg.norm(self.pos[s] - self.pos[scorer]) < 45:
                    tgt[s] = self.pos[scorer] + unit(self.pos[s] - self.pos[scorer]) * 1.2
                    urg[s] = 0.7
        elif since < 16:
            for s in self.outfield(team):
                if np.linalg.norm(self.pos[s] - self.pos[scorer]) < 12:
                    tgt[s] = self.pos[scorer] + unit(self.pos[s] - self.pos[scorer]) * 1.0

    def steer(self, tgt, urg):
        vmax = self.vmax()
        d = tgt - self.pos
        dist = np.linalg.norm(d, axis=1) + 1e-6
        jog = np.clip(0.5 + 0.25 * dist, 0.5, 0.5 * vmax)
        jog = np.where(dist < 0.6, 0.0, jog)
        cap = np.where(urg > 0, urg * vmax, jog)
        want = np.minimum(cap, dist * 1.8)
        v_des = d / dist[:, None] * want[:, None]

        diff = self.pos[:, None, :] - self.pos[None, :, :]
        dd = np.linalg.norm(diff, axis=2) + np.eye(22) * 100
        push = np.clip(1.1 - dd, 0, None) / 1.1
        v_des += (diff / dd[..., None] * push[..., None]).sum(axis=1) * 2.0

        dv = v_des - self.vel
        n = np.linalg.norm(dv, axis=1) + 1e-9
        lim = self.accel * DT * 1.25
        self.vel += dv * np.minimum(1, lim / n)[:, None]
        sp = np.linalg.norm(self.vel, axis=1) + 1e-9
        self.vel *= np.minimum(1, vmax / sp)[:, None]
        self.pos += self.vel * DT

    # --------------------------------------------------------------- output

    def frame_array(self) -> np.ndarray:
        return np.stack(self.frames)
