# Confidence wording

Read this before you give a key message a confidence level or a prediction a probability. The wording is fixed, so that "likely" means the same thing in every report. The report's legend shows the same tables. Examples use invented names only (Example Pharma, Competitor A).

1. **Confidence is about the evidence behind a key message.** Pick the level whose meaning fits. These are the engine's own words and you never reword them.

| Level | Meaning |
|---|---|
| `high` | High confidence: several independent sources agree. |
| `medium` | Medium confidence: the evidence points one way but has gaps. |
| `low` | Low confidence: the evidence is thin or conflicting. |

   Why: a reader should know how far to lean on a message without reading the chain.

2. **A key message carries exactly one confidence level.** It is `high`, `medium` or `low`. Never two, never a level in between, never left out. Choose it by the meaning in the table, not by how sure the text sounds. Two sources that are not independent count as one, so they do not make a message `high`.
   Why: the level is a claim about the sources, and a source count is easy to check.

3. **A probability word is a word for a range.** Use a word only with the meaning of its range. Write none in the text of a key message: the report adds the word to a prediction, from its number, and `analysis-format.md` says the same.

| Range | Word |
|---|---|
| 95-100 | almost certain |
| 80-94 | very likely |
| 60-79 | likely |
| 40-59 | about as likely as not |
| 20-39 | unlikely |
| 5-19 | very unlikely |
| 0-4 | remote |

   Why: "likely" for a 55 in 100 chance would be false precision turned the wrong way.

4. **A prediction carries a number from 1 to 99.** Write only the number in `probability`. The report adds the word that belongs to it. Never write 0 or 100, because the future is never that sure.
   Why: the program picks the word, so the word and the number cannot disagree.

5. **A probability stands only in a prediction.** Its number, such as 65, stands in the `probability` field, and the report shows the word for its range next to it. No other text gives a probability, as a word or as a number.
   Why: a single number looks more exact than the evidence allows, and a word in a text would have no number to check it against.

6. **The legend shows this scale.** The report's legend lists the confidence levels and the probability words with their ranges. This scale is this project's own.
   Why: a reader finds the same wording in the legend as in the text.

7. **A prediction and a confidence level are different things.** The confidence level says how well the facts support a message today. The probability says how likely a stated event is by a stated date. A `low` confidence message may have a prediction, and a prediction does not raise the message's confidence.
   Why: mixing them lets a guess about the future pass for a finding.

```json radar-constants
{
  "confidence": {
    "high": "High confidence: several independent sources agree.",
    "medium": "Medium confidence: the evidence points one way but has gaps.",
    "low": "Low confidence: the evidence is thin or conflicting."
  },
  "probability": [
    [95, "95-100", "almost certain"],
    [80, "80-94", "very likely"],
    [60, "60-79", "likely"],
    [40, "40-59", "about as likely as not"],
    [20, "20-39", "unlikely"],
    [5, "5-19", "very unlikely"],
    [0, "0-4", "remote"]
  ]
}
```
