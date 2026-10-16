import pytest
from gymnasium.utils.env_checker import check_env

from sotonship26.train import make_env


@pytest.mark.parametrize("name", ["streets", "water"])
def test_env_passes_gymnasium_checks(name):
    check_env(make_env(name, {"max_iters": 3}), skip_render_check=True)


def test_episode_runs_one_step_per_bin():
    env = make_env("streets", {"max_iters": 3})
    env.reset(seed=0)
    steps, done = 0, False
    while not done:
        _, reward, terminated, truncated, _ = env.step(env.action_space.sample())
        assert reward <= 0
        steps += 1
        done = terminated or truncated
    assert steps == env.n_bins
