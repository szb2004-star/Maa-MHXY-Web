"""Run the original custom registrations without auto-installing dependencies."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / 'agent'))


def main():
    from maa.agent.agent_server import AgentServer
    from maa.toolkit import Toolkit
    import custom  # noqa: F401 -- decorators register original actions, recognitions and sinks

    Toolkit.init_option(os.environ['MHXY_INSTANCE_DIR'])
    if not AgentServer.start_up(sys.argv[1]):
        raise RuntimeError('自定义 Agent 启动失败')
    try:
        AgentServer.join()
    finally:
        AgentServer.shut_down()


if __name__ == '__main__':
    main()
