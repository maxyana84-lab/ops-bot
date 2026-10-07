from app.config import Settings, Target
from app.main import build_application


def test_application_wires_handlers_and_health_job():
    settings = Settings(
        telegram_token="123:abc",
        webhook_secret="x" * 16,
        alert_chat_ids=(1,),
        allowed_chat_ids=(1,),
        targets=(Target("api", "https://api.test"),),
    )
    app = build_application(settings)
    commands = {cmd for h in app.handlers[0] for cmd in h.commands}
    assert {"start", "status", "targets", "mute", "unmute", "uptime", "help"} <= commands
    assert [job.name for job in app.job_queue.jobs()] == ["periodic_check"]
