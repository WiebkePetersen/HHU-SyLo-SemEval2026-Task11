Translate sentences written in ANY of the following languages into First-Order Logic
in Otter-Syntax:
German (de), Spanish (es), French (fr), Italian (it), Dutch (nl), Portuguese (pt),
Russian (ru), Chinese (zh), Swahili (sw), Bengali (bn), Telugu (te).

- Use 'all x (A(x) -> B(x))' for universals and 'exists x (A(x) & B(x))' for existentials.
- 'No A is B' maps to 'all x (A(x) -> -B(x))'.
- Use consistent PredicateNames (PascalCase) for identical concepts.
- Return ONLY a Python list of strings.
