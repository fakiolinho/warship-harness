# The real sandbox boundary.
#
# read_file is confined to the workspace; run_command cannot be, because
# `sh -c` reaches anything the invoking user reaches. Rather than pretend
# otherwise, run the mission in a container whose filesystem IS the
# workspace: then "outside the workspace" holds nothing worth reaching.
#
# Built and exercised by CI on every push: selfcheck.py runs inside the
# image, and a step asserts the agent user cannot write to /etc. The
# mounts below are NOT covered by that, since CI runs without them.
#
#   mkdir -p data
#   docker build -t warship-harness .
#   docker run --rm \
#     -e ANTHROPIC_API_KEY \
#     -e WARSHIP_NONINTERACTIVE=1 \
#     -e WARSHIP_LEDGER=/work/data/ledger.jsonl \
#     -u "$(id -u):$(id -g)" \
#     -v "$PWD/missions:/work/missions" \
#     -v "$PWD/data:/work/data" \
#     warship-harness python run.py missions/demo
#
# Bind mounts belong to the host user, so -u avoids the container user
# being unable to write to them. Without the data mount the ledger is
# written inside the container and discarded with it.
#
# Network: this image can reach the Anthropic API, which a mission needs.
# If a mission does not need the wider internet, run it behind an egress
# proxy that allows only api.anthropic.com. `--network none` will not work:
# the agent cannot call the model without a network.

FROM python:3.12-slim

# Non-root: the container is the boundary, but a root process inside it is
# still a larger blast radius than it needs to be.
RUN useradd --create-home --shell /usr/sbin/nologin agent

WORKDIR /work
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=agent:agent harness/ ./harness/
COPY --chown=agent:agent agent.py run.py finops.py selfcheck.py seed_ledger.py ./

# The agent owns its workspace and nothing else on the filesystem.
RUN mkdir -p /work/missions && chown -R agent:agent /work
USER agent

# No TTY in a container, so the gate declines every "ask" rather than
# blocking forever on a prompt nobody will answer.
ENV WARSHIP_NONINTERACTIVE=1 \
    PYTHONUNBUFFERED=1

CMD ["python", "selfcheck.py"]
