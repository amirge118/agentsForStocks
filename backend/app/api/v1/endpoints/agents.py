"""GET /api/v1/agents — what the system analyses and how the recommendation is weighted."""

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.container import Container
from app.schemas.api import AgentInfo, AgentProfileOut

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentInfo])
async def list_agents(container: Container = Depends(get_container)) -> list[AgentInfo]:
    levels = container.registry.execution_levels()
    ordered = [name for level in levels for name in level]  # execution order
    profiles = container.agent_context.profiles
    infos = []
    for spec in sorted(container.registry.all(), key=lambda s: ordered.index(s.name)):
        profile = profiles.resolve(spec.name, spec.agent_cls.default_profile)
        provider = profile.provider or container.llm.default_provider
        infos.append(
            AgentInfo(
                name=spec.name,
                description=spec.description,
                depends_on=list(spec.depends_on),
                recommendation_weight=spec.recommendation_weight,
                profile=AgentProfileOut(
                    provider=provider,
                    model=profile.model,
                    skills=list(profile.skills),
                    use_llm=profile.use_llm,
                ),
            )
        )
    return infos
