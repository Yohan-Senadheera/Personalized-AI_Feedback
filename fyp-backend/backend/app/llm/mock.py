from typing import Dict, Any

class MockLLM:
    def generate_json(self, system: str, user: str) -> Dict[str, Any]:
        s = (system + " " + user).lower()

        if "correctness agent" in s:
            return {
                "q_scores": {"1": 2, "2": 3, "3": 2},
                "key_points_found": {
                    "1": ["stable endpoint", "pods", "load balancing"],
                    "2": ["ClusterIP internal", "NodePort external"],
                    "3": ["restrict traffic", "frontend->backend"]
                }
            }

        if "misconception agent" in s:
            return {
                "misconceptions": [],
                "missing_points": {
                    "1": ["Services select pods using labels"],
                    "2": ["Ingress/LoadBalancer commonly used"],
                    "3": ["default deny behavior requires policy design"]
                }
            }

        if "clarity agent" in s:
            return {
                "clarity_score": 0.75,
                "writing_suggestions": [
                    "Use 1–2 more technical terms precisely (e.g., label selector, service discovery).",
                    "Keep each answer 2–4 sentences for clarity."
                ]
            }

        if "personalization agent" in s:
            return {
                "personalized_notes": [
                    "You are improving on Kubernetes networking basics.",
                    "Focus next on NetworkPolicy rule directions (ingress vs egress)."
                ],
                "recommended_next_topics": ["Service selectors", "Ingress vs NodePort", "NetworkPolicy ingress/egress"]
            }

        if "feedback qa agent" in s:
            # pretend the feedback is good enough
            return {"quality_score": 0.82, "issues": []}

        # synthesizer default
        return {
            "grade": 78,
            "confidence": 0.7,
            "final_feedback": "Good work overall. Improve by adding label-selector detail and mention production exposure via Ingress/LoadBalancer.",
            "concept_scores": {"service": 0.75, "clusterip_nodeport": 0.8, "networkpolicy": 0.7}
        }
