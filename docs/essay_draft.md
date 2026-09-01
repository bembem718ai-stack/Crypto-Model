# Essay draft — skeleton

**~650 words. First person. PLACEHOLDER-marked where only the author can
speak.** This is scaffolding and evidence, not a finished essay: the
connective tissue is deliberately thin so it does not put words in your mouth.

Every number below traces to a document in the repo. Do not add one that
does not.

---

## The arc

> built a thing to find an edge → built the machinery to check myself → the
> machinery kept catching me before the market could → ended with a true
> nothing, and understood why that was the rarer result

---

## Draft

**[WHY I STARTED — yours]**
*Two or three sentences. What actually pulled you in — the money, the
puzzle, a specific moment. Resist making it sound noble in hindsight. The
honest version is more convincing than the tidy one, and an essay that
starts with "I wanted to beat the market" earns the ending far better than
one that starts with "I was curious about epistemology".*

---

I built a trading model. It looked for a pattern called a volatility squeeze,
scored it against technical indicators, and published a signal when the score
cleared a bar. Then I did the thing that turned a hobby project into
something else: before running a test, I wrote down what would count as
passing, and I wrote it where I could not later edit it.

That one habit produced 249 registered hypotheses and, eventually, zero
supported claims.

The interesting part is not that nothing worked. Most things do not work. The
interesting part is how hard I had to work to be sure of it — because I kept
catching my own tools cheating on my behalf.

**Moment one — the null that was rigging the game for me.**
To decide whether a rule beat luck, I compared it against a random version of
itself. But my random version re-shuffled its holdings every day, while the
real rule traded weekly. The fake version paid **13.6 times** the trading
costs. It was losing money for reasons that had nothing to do with skill, and
every rule I tested was about to be measured against that crippled opponent.
I found it by checking whether the null actually had the property I claimed
for it. It did not. **I had built a machine for producing good news and very
nearly used it.**

**Moment two — the number I had to take back.**
For a while I had one supported claim: a strategy that measured +0.237 on my
data. Then I extended the dataset by a year and re-ran it. It came back
**−0.167**. Nothing had broken. Both numbers were correct for the data they
were computed on — the window had simply moved. Later I profiled the same
statistic across fifty different windows and found the original was outside
all of them. **My best result had needed one specific start date and one
specific end date, together.** I removed it from the claims document. That
left zero.

**Moment three — the test I did not run.**
At the end I built a map of the market's structure: volatility clustering,
jump frequency, whether Bitcoin leads the smaller coins. I gave myself
permission to draw exactly one new hypothesis from it, because a document
with hundreds of measured cells will contain patterns that are pure chance.
I read it. The most interesting thing in it was that the folklore everyone
repeats — Bitcoin leads the altcoins — **was not true at the timescale I
measured**: the correlation was real but simultaneous, not leading. Nothing
else had a mechanism behind it.

So I spent nothing. The slot is still there, unused.

**[THE MOMENT IT CHANGED FOR ME — yours]**
*One paragraph. Which of the three above actually landed, or a fourth I do
not know about. What did you feel when you found it — irritation, dread,
something like relief? Be specific about the feeling; that is the part no
document in the repo can supply, and it is what makes this yours rather than
a lab report.*

---

I have 545 automated tests, a sealed six-month holdout I have never looked
at, and three programs registered to run in 2027 and 2028 against data that
does not exist yet — so I cannot possibly tune them to it.

And I have no edge. Eight published trades: three winners, five losers.

**[WHAT I DO DIFFERENTLY NOW — yours]**
*Two or three sentences. Where this shows up outside the project — how you
read a statistic in the news, argue a point, handle being wrong. Make it
concrete and small. "I think about sample size now" is weaker than one
specific instance of you doing it.*

---

The result I ended with is a nothing. But it is a **true** nothing, and I can
show exactly why — which is rarer, and much harder, than a number that looks
good.

---

## Notes for the author

**Three concrete moments, ranked by how well they carry an essay:**

1. **The 13.6× null.** Strongest. It is you catching yourself, the stakes are
   legible in one number, and it needs no finance background to land.
2. **#171's sign flip.** Best emotional beat — you took something away from
   yourself and the document proves it. Slightly harder to explain.
3. **Not spending the #250 slot.** Best ending, weakest opening. Restraint is
   hard to dramatise but lands well after the first two have earned it.

**Pick two, not three.** All three at this length makes a list. Two makes an
argument.

**Do not soften the ending into a lesson about perseverance.** The honest
version is that you looked hard, found nothing, and can prove the nothing is
real. That is the whole essay. Do not add that you "learned more than any
success could have taught" — it is a cliché and, worse, it is a claim you
have not tested.

**Every number is checkable:** 249 registered hypotheses, 545 tests, 13.6×,
+0.237 → −0.167, 8 published episodes at +1.00R, zero supported claims. If a
reader looks, the repo agrees. Keep it that way.
