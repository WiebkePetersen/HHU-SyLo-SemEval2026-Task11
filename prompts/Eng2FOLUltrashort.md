Translate English sentences into First-Order Logic for the Otter prover.
- Use 'all x (A(x) -> B(x))' for universals and 'exists x (A(x) & B(x))' for existentials.
- 'No A is B' maps to 'all x (A(x) -> -B(x))'.
- Use consistent PredicateNames (PascalCase) for identical concepts.
- Return ONLY a Python list of strings.
