def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """在 pytest 结束时输出搜索评测汇总指标。"""

    summary = getattr(config, "_search_eval_summary", None)
    if not summary:
        return

    terminalreporter.write_sep("=", "Search eval summary")
    terminalreporter.write_line(f"Total cases: {summary['total_cases']}")
    terminalreporter.write_line(f"Top1 hits: {summary['top1_hits']}")
    terminalreporter.write_line(f"Top3 hits: {summary['top3_hits']}")
    terminalreporter.write_line(f"Zero results: {summary['zero_results']}")
    terminalreporter.write_line(f"Top1 Accuracy: {summary['top1_accuracy']:.2%}")
    terminalreporter.write_line(f"Top3 Accuracy: {summary['top3_accuracy']:.2%}")
    terminalreporter.write_line(f"Zero Result Rate: {summary['zero_result_rate']:.2%}")
