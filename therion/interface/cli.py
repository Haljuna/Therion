"""Interface de linha de comando simples para a V0."""

import sys
from therion.core.orchestrator import Orchestrator
from therion.config import load_config, save_config


def run_interaction(user_input: str, confirm_input: str, simulate: bool = True) -> None:
    """Executa uma interação programática para testes e demonstrações."""
    orchestrator = Orchestrator(simulate=simulate)
    print(f"Usuário:\n{user_input}\n")
    print("Therion:")
    result = orchestrator.process_command(user_input)
    print(result.message)

    if result.registered_plan_id is not None:
        orchestrator.ack_registered_plan_displayed(result.registered_plan_id)

    if result.plan_candidate_id is not None:
        ack = orchestrator.ack_plan_displayed(result.plan_candidate_id)
        if ack.status == "displayed_not_registered":
            print("Este plano foi exibido, mas não pôde ser registrado nesta sessão. Por isso, ele não poderá ser recuperado depois por referências como “mesmo plano”, “plano anterior” ou “primeiro plano”.")

    if result.status == "awaiting_confirmation" and result.plan:
        print(f"\nUsuário:\n{confirm_input}\n")
        confirmed = orchestrator.confirmation_handler.evaluate_response(confirm_input)
        if confirmed is None:
            print("Therion:\nResposta inválida. Operação cancelada por precaução.")
            return

        final_result = orchestrator.confirm_and_execute(result.plan, confirmed=confirmed)
        print("Therion:")
        print(final_result.message)


def main() -> None:
    """Ponto de entrada interativo da CLI da V0 (modo real por padrão)."""
    # Suporta flag --simulate se o usuário quiser explicitamente rodar em simulação
    from therion.autonomy.windows import SingleInstance, build_runtime
    instance = SingleInstance()
    if not instance.acquired:
        instance.close()
        print('Therion já está aberto. Use a interface ativa para evitar operações concorrentes.')
        return
    simulate = "--simulate" in sys.argv
    config = load_config()
    agent_kwargs = {}
    if config.get('agent', {}).get('enabled') is True:
        from therion.core.ai_provider_ollama import OllamaProvider
        from therion.core.ai_core import AICore
        ai=config.get('ai',{})
        if ai.get('enabled') is True:
            provider=OllamaProvider(model=ai['model'],timeout=ai.get('timeout_seconds',90),
                endpoint=ai['endpoint'],think=ai.get('think'))
            agent_kwargs['ai_core']=AICore(provider,available_intents=['abrir aplicativo','buscar segundo cérebro','calendário hoje','criar evento calendário'])
        if config.get('calendar',{}).get('enabled') is True:
            from therion.calendar.google_adapter import GoogleCalendarAdapter
            agent_kwargs['calendar_adapter']=GoogleCalendarAdapter(time_zone=config['calendar'].get('time_zone','America/Sao_Paulo'))
    orchestrator = Orchestrator(simulate=simulate,
        agent_config=config.get('agent', {}),
        **agent_kwargs,
        autonomy_runtime_factory=lambda:build_runtime(load_config,save_config))

    mode_label = "Modo Simulado" if simulate else "Modo Real Controlado (Windows)"
    print(f"Therion V0 - Interface de Texto ({mode_label})")

    try:
        command = input("Usuário:\n").strip()
        if not command:
            return

        print("\nTherion:")
        result = orchestrator.process_command(command)
        print(result.message)

        if result.registered_plan_id is not None:
            orchestrator.ack_registered_plan_displayed(result.registered_plan_id)

        if result.plan_candidate_id is not None:
            ack = orchestrator.ack_plan_displayed(result.plan_candidate_id)
            if ack.status == "displayed_not_registered":
                print("Este plano foi exibido, mas não pôde ser registrado nesta sessão. Por isso, ele não poderá ser recuperado depois por referências como “mesmo plano”, “plano anterior” ou “primeiro plano”.")

        if result.status == "awaiting_confirmation" and result.plan:
            resp = input("\n").strip()
            confirmed = orchestrator.confirmation_handler.evaluate_response(resp)
            if confirmed is None:
                print("\nTherion:\nResposta não reconhecida. Operação cancelada por precaução.")
                return

            final_result = orchestrator.confirm_and_execute(result.plan, confirmed=confirmed)
            print(f"\nTherion:\n{final_result.message}")

    except (KeyboardInterrupt, EOFError):
        print("\nSessão encerrada.")
    finally:
        orchestrator.close()
        instance.close()


if __name__ == "__main__":
    main()
