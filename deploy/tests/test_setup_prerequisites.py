import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import setup_prerequisites as prerequisites


class PrerequisiteTests(unittest.TestCase):
    def test_declined_install_executes_nothing(self):
        with patch('builtins.input', return_value='no'), patch.object(prerequisites.subprocess, 'run') as run:
            self.assertFalse(prerequisites.execute([['brew', 'install', 'awscli']]))
        run.assert_not_called()

    def test_non_mac_install_is_rejected(self):
        with patch.object(prerequisites.platform, 'system', return_value='Linux'):
            with self.assertRaisesRegex(ValueError, 'macOS only'):
                prerequisites.menu()

    def test_missing_brew_does_not_run_install(self):
        with patch.object(prerequisites.shutil, 'which', return_value=None), patch.object(prerequisites.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'Homebrew first'):
                prerequisites.install(['awscli'])
        run.assert_not_called()

    def test_wrong_java_and_node_versions_are_flagged(self):
        with patch.object(prerequisites, 'CHECKS', prerequisites.CHECKS[14:16]), patch.object(prerequisites, 'activate_tools'), patch.object(prerequisites, 'probe', side_effect=[(True, 'openjdk version "21.0.1"'), (True, 'v22.0.0')]):
            self.assertEqual(len(prerequisites.check()), 2)

    def test_existing_runtime_is_opened_without_installing(self):
        with patch.object(prerequisites.Path, 'exists', return_value=True), patch.object(prerequisites, 'execute') as execute, patch.object(prerequisites, 'install') as install:
            prerequisites.docker()
        execute.assert_called_once_with([['open', '-a', 'OrbStack']])
        install.assert_not_called()

    def test_install_all_cancellation_makes_no_changes(self):
        with patch.object(prerequisites, 'activate_tools'), patch.object(prerequisites.Path, 'exists', return_value=True), patch('builtins.input', return_value='no'), patch.object(prerequisites, 'execute') as execute, patch.object(prerequisites, 'homebrew') as brew:
            prerequisites.install_all()
        execute.assert_not_called()
        brew.assert_not_called()

    def test_install_all_pauses_for_apple_dialog(self):
        with patch.object(prerequisites, 'activate_tools'), patch.object(prerequisites.Path, 'exists', return_value=True), patch('builtins.input', return_value='yes'), patch.object(prerequisites, 'probe', return_value=(False, 'missing')), patch.object(prerequisites, 'execute') as execute, patch.object(prerequisites, 'homebrew') as brew:
            prerequisites.install_all()
        execute.assert_called_once_with([['xcode-select', '--install']], confirm=False)
        brew.assert_not_called()

    def test_install_all_reuses_docker_and_checks_after_install(self):
        with patch.object(prerequisites, 'activate_tools'), patch.object(prerequisites.Path, 'exists', return_value=True), patch('builtins.input', return_value='yes') as prompt, patch.object(prerequisites, 'probe', return_value=(True, 'installed')), patch.object(prerequisites, 'execute') as execute, patch.object(prerequisites, 'homebrew') as brew, patch.object(prerequisites.shutil, 'which', return_value='/opt/homebrew/bin/brew'), patch.object(prerequisites, 'check') as check:
            prerequisites.install_all()
        prompt.assert_called_once()
        brew.assert_called_once_with(confirm=False)
        self.assertEqual(execute.call_count, 2)
        commands = execute.call_args_list[0].args[0]
        self.assertIn('openjdk@25', commands[0])
        self.assertIn('session-manager-plugin', commands[1])
        execute.assert_called_with([['open', '-a', 'OrbStack']], confirm=False)
        check.assert_called_once()

    def test_path_activation_is_idempotent(self):
        with patch.dict(os.environ, {'PATH': '/usr/bin'}), patch.object(prerequisites.platform, 'system', return_value='Darwin'), patch.object(prerequisites.platform, 'machine', return_value='arm64'), patch.object(prerequisites.Path, 'is_dir', return_value=True), patch.object(prerequisites.Path, 'exists', return_value=True):
            prerequisites.activate_tools()
            first = os.environ['PATH']
            prerequisites.activate_tools()
            self.assertEqual(first, os.environ['PATH'])
            self.assertLess(first.index('/opt/homebrew/opt/node@24/bin'), first.index('/opt/homebrew/bin'))


if __name__ == '__main__':
    unittest.main()
