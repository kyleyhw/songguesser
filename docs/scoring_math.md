# Scoring curve

## The curve

For a guess landing at elapsed time $t$ within a round of duration $T$,
the score is

$$s(t) = \left\lfloor B \cdot \left( 1 - \tfrac{t}{T} \right) \right\rfloor, \qquad t \in [0, T],$$

with the base $B$ depending on what was guessed:

- $B = B_{\text{full}} = 1000$ when the player has just identified
  *both* the title and the artist this round.
- $B = B_{\text{part}} = 500$ when the player has just identified
  exactly one of the two for the first time this round.

Outside $[0, T]$ the score is clamped to zero.

## Lattice and "no-double-pay"

Each player has a per-round "kind" that lives on the lattice

$$\mathrm{NONE} \;\to\; \{\mathrm{TITLE},\ \mathrm{ARTIST}\} \;\to\; \mathrm{BOTH},$$

with the join $\mathrm{TITLE} \sqcup \mathrm{ARTIST} = \mathrm{BOTH}$.
Scoring is awarded only on a transition that strictly raises the kind:

- $\mathrm{NONE} \to \mathrm{TITLE}$ or $\mathrm{NONE} \to \mathrm{ARTIST}$:
  award $s_{\text{part}}(t) = \lfloor B_{\text{part}} (1 - t/T) \rfloor$.
- $\mathrm{TITLE} \to \mathrm{BOTH}$ or $\mathrm{ARTIST} \to \mathrm{BOTH}$:
  award the *top-up* needed to bring the running total to
  $s_{\text{full}}(t)$ — see below.
- $\mathrm{NONE} \to \mathrm{BOTH}$: award $s_{\text{full}}(t)$.
- Any transition that does not raise the kind: zero.

## Top-up rule

The top-up rule deserves attention because it prevents a perverse
incentive. Suppose the player guesses the title at time $t_1$, earning
$s_{\text{part}}(t_1)$, and then the artist at time $t_2 > t_1$. Without
a correction, the player's round total would be

$$\mathrm{total} = s_{\text{part}}(t_1) + s_{\text{part}}(t_2),$$

which can be *less than* the score for an equivalent single $\mathrm{BOTH}$
guess at $t_2$ ($s_{\text{full}}(t_2) = 2 s_{\text{part}}(t_2)$). A fast
partial guess would actually *hurt* the player.

Instead we award

$$\Delta_2 = \max\!\left( s_{\text{full}}(t_2) - s_{\text{part}}(t_2),\ 0 \right)$$

at $t_2$, so that

$$\mathrm{total} = s_{\text{part}}(t_1) + \Delta_2 \geq s_{\text{full}}(t_2).$$

In other words, the player who completes both at $t_2$ never earns less
than the player who completed both with a single guess at $t_2$, and
typically earns more (because $s_{\text{part}}(t_1) > s_{\text{part}}(t_2)$
when $t_1 < t_2$). This makes early partial guesses always
non-decreasing in expected value, restoring the incentive to guess
fast.

## Why linear

A linear curve has two virtues over an exponential one:

1. **Calibration is straightforward.** Players quickly learn that
   "around half-way through the round is half-credit", which is much
   harder to internalise for an exponential curve.
2. **The top-up arithmetic stays in integers.** Both $s_{\text{full}}$
   and $s_{\text{part}}$ are integer functions of $t$, and the top-up
   uses only their difference; no floating-point subtleties.

The exponent $\gamma > 1$ used for the cover-reveal curve (see
`docs/reveal_math.md`) is *not* used here on purpose: the cover reveal
should accelerate near the end (so most of the visible obscuration
happens early), but the score curve should *not* favour the late game,
because that would make solo guessers dominate over groups who
co-deduce mid-round.
