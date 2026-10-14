from leados.schemas import AssertionType, Claim, ResearchOutput


class MockLLMProvider:
    name = "mock_llm"
    model = "deterministic-template-v1"

    async def research(self, context: dict) -> ResearchOutput:
        vertical = context["vertical"]
        signal = context["signal"]
        service = context["retrieved_services"][0]
        ids = context["evidence_ids"]
        return ResearchOutput(
            inferences=[
                Claim(
                    type=AssertionType.INFERENCE,
                    text=f"The reported event may increase the need to address: {vertical['typical_problem'].lower()}",
                    evidence_ids=ids,
                )
            ],
            commercial_thesis=f"Validate whether {service.lower()} would help; a need is inferred, not confirmed.",
            why_now=f"The dated {signal['name'].lower()} event creates a reason to review operational readiness.",
            outreach_angle=f"Offer a focused conversation about {service.lower()} without assuming a confirmed gap.",
            need=min(1.0, signal["base_strength"] / 25),
            mandate_value=0.8,
        )
