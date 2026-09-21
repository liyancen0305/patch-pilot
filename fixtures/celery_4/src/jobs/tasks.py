from celery import Celery

app = Celery("jobs")
app.config_from_object("jobs.config")


@app.task
def add_tax(amount: int, rate_percent: int) -> int:
    if amount < 0:
        raise ValueError("amount must be nonnegative")
    return amount + amount * rate_percent // 100
