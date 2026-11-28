def test_advanced_workspace_ui_extensions_are_importable():
    import advanced_workspace as workspace

    assert callable(workspace.render_market_intelligence)
    assert callable(workspace.render_portfolio_persistence)
    assert callable(workspace.render_multi_asset_backtest)
    assert callable(workspace.render_research_exports)
