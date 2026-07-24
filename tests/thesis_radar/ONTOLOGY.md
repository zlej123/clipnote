# Thesis Radar claim ontology

The extraction target is an attributable proposition, not a topic or summary.

| Type | Label when | Do not label when |
|---|---|---|
| `factual_claim` | A present or past assertion can be checked against evidence | The speaker only asks a question |
| `inference` | The speaker derives a conclusion from stated observations | The conclusion is explicitly about the future |
| `prediction` | The assertion concerns a future event, result, or price | It is only a conditional scenario |
| `opinion` | The statement is evaluative and not objectively decidable | It contains a separately testable factual assertion |
| `rumor` | The speaker relays information with no identified authoritative source | A named primary source supports it |
| `recommendation` | The speaker explicitly recommends buying, selling, or holding | The speaker merely describes personal ownership |

Split compound claims when each part can be verified independently. Preserve
the speaker's certainty and distinguish direct assertions from third-party
quotations.

