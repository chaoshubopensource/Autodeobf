import tempfile
import os
import time

class ExecutionEngine:
    def __init__(self, max_time=10):
        self.max_execution_time = max_time
        self.execution_log = []

    def execute_code_safely(self, lua_code, use_environment=True):
        start_time = time.time()
        try:
            import lupa
            from lupa import LuaRuntime

            lua = LuaRuntime(unpack_returned_tuples=True)

            output_lines = []

            # Redireciona o print do Lua
            lua.globals().print = lambda *args: output_lines.append(
                "\t".join(str(a) for a in args)
            )

            # Remove funções perigosas
            lua.execute("os.execute = nil")
            lua.execute("io.popen = nil")
            lua.execute("require = nil")
            lua.execute("dofile = nil")
            lua.execute("loadfile = nil")

            lua.execute(lua_code)

            elapsed = time.time() - start_time
            output_text = "\n".join(output_lines)

            result = {
                'successful': True,
                'output_text': output_text,
                'error_text': '',
                'exit_code': 0,
                'duration': elapsed,
                'timed_out': False
            }

        except ImportError:
            elapsed = time.time() - start_time
            result = {
                'successful': False,
                'output_text': '',
                'error_text': 'Biblioteca lupa não instalada. Adicione lupa ao requirements.txt',
                'exit_code': -1,
                'duration': elapsed,
                'timed_out': False
            }
        except Exception as e:
            elapsed = time.time() - start_time
            result = {
                'successful': False,
                'output_text': '',
                'error_text': str(e),
                'exit_code': -1,
                'duration': elapsed,
                'timed_out': False,
                'error_occurred': True
            }

        self.execution_log.append(result)
        return result

    def process_script_file(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                file_content = f.read()

            execution_result = self.execute_code_safely(file_content)

            return {
                'target_file': file_path,
                'content_size': len(file_content),
                'execution_details': execution_result,
                'log_entries': len(self.execution_log)
            }

        except Exception as e:
            return {
                'target_file': file_path,
                'error_message': str(e)
            }

    def get_execution_summary(self):
        if not self.execution_log:
            return "Nenhuma execução registrada"

        successful_count = sum(1 for r in self.execution_log if r['successful'])
        total_count = len(self.execution_log)

        return {
            'total_executions': total_count,
            'successful_executions': successful_count,
            'success_percentage': (successful_count / total_count * 100) if total_count > 0 else 0,
            'average_duration': sum(r['duration'] for r in self.execution_log) / total_count if total_count > 0 else 0,
            'timeout_count': sum(1 for r in self.execution_log if r.get('timed_out', False))
        }
