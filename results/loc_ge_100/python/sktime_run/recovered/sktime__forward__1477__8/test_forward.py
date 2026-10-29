"""Tests for ``MIRAForPrediction.forward`` in ``sktime.libs.mira.modeling_mira``."""

import warnings

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

from torch import nn  # noqa: E402

import sktime.libs.mira.modeling_mira as modeling_mira  # noqa: E402
from sktime.libs.mira.configuration_mira import MIRAConfig  # noqa: E402
from sktime.libs.mira.modeling_mira import MIRAForPrediction  # noqa: E402

HIDDEN_SIZE = 16
NUM_LAYERS = 1
NUM_HEADS = 2
NUM_KV_HEADS = 1
HEAD_DIM = HIDDEN_SIZE // NUM_HEADS
BATCH = 2
SEQ = 5

ODE_SKIPPED_MSG = "next_target_time_values not provided during training"


def _config(**overrides):
    """Build a tiny MIRAConfig that is cheap to instantiate in tests."""
    kwargs = {
        "input_size": 1,
        "hidden_size": HIDDEN_SIZE,
        "intermediate_size": 32,
        "horizon_lengths": [1],
        "num_hidden_layers": NUM_LAYERS,
        "num_attention_heads": NUM_HEADS,
        "num_key_value_heads": NUM_KV_HEADS,
        "hidden_act": "silu",
        "num_experts_per_tok": 2,
        "num_experts": 4,
        "max_position_embeddings": 64,
        "use_cache": True,
        "use_dense": False,
        "time_aware_rotary": True,
        "use_terminal_ode": False,
        "apply_aux_loss": True,
        "attention_dropout": 0.0,
        "ode_func_hidden_dims": [4],
        "ode_func_activation": "silu",
        "ode_solver_method": "rk4",
    }
    kwargs.update(overrides)
    return MIRAConfig(**kwargs)


def _model(training=False, **overrides):
    """Build a small randomly-initialised model in a fixed (deterministic) state."""
    torch.manual_seed(0)
    model = MIRAForPrediction(_config(**overrides))
    model.train(training)
    return model


def _inputs(batch=BATCH, seq=SEQ, seed=1):
    """Return fresh ``(input_ids, time_values)`` tensors."""
    generator = torch.Generator().manual_seed(seed)
    input_ids = torch.randn(batch, seq, generator=generator)
    time_values = torch.arange(seq, dtype=torch.float32).unsqueeze(0).expand(batch, seq)
    return input_ids, time_values.clone()


class _RecordingODEBlock(nn.Module):
    """Stand-in for ``TerminalODEBlock`` that records its inputs.

    ``forward`` returns ``h_N * scale`` (``scale`` is learnable so gradients can
    be traced) unless ``offset`` is not ``None``, in which case ``h_N + offset``
    is returned.
    """

    def __init__(self, offset=None):
        super().__init__()
        self.scale = nn.Parameter(torch.tensor(1.0))
        self.offset = offset
        self.calls = []

    def forward(self, h_N, t_N, t_Nplus1):
        self.calls.append((h_N, t_N, t_Nplus1))
        if self.offset is None:
            return h_N * self.scale
        return h_N + self.offset


class TestForwardInference:
    """Behaviour of ``forward`` when no labels are given (inference mode)."""

    def test_returns_output_object_with_expected_logit_shape(self):
        model = _model()
        input_ids, time_values = _inputs()

        output = model(input_ids=input_ids, time_values=time_values)

        assert isinstance(output, modeling_mira.MoeCausalLMOutputWithPast)
        assert output.logits.shape == (BATCH, 1, 1)
        assert torch.isfinite(output.logits).all()
        # no labels -> no losses
        assert output.loss is None
        assert output.aux_loss is None
        # cache is populated by the decoder and passed through unchanged
        assert output.past_key_values is not None
        # default flags from the config are both False
        assert output.hidden_states is None
        assert output.attentions is None

    def test_past_key_values_expose_per_layer_kv_cache(self):
        model = _model()
        input_ids, time_values = _inputs()

        output = model(input_ids=input_ids, time_values=time_values)

        cache = output.past_key_values
        assert isinstance(cache, tuple)
        assert len(cache) == NUM_LAYERS
        key_states, value_states = cache[0]
        expected_shape = (BATCH, NUM_KV_HEADS, SEQ, HEAD_DIM)
        assert key_states.shape == expected_shape
        assert value_states.shape == expected_shape

    def test_repeated_calls_are_deterministic_in_eval_mode(self):
        model = _model()
        input_ids, time_values = _inputs()

        first = model(input_ids=input_ids.clone(), time_values=time_values).logits
        second = model(input_ids=input_ids.clone(), time_values=time_values).logits

        assert torch.allclose(first, second, atol=0.0)

    def test_input_ids_of_two_and_three_dimensions_are_equivalent(self):
        model = _model()
        input_ids, time_values = _inputs()

        from_2d = model(input_ids=input_ids.clone(), time_values=time_values).logits
        from_3d = model(
            input_ids=input_ids.clone().unsqueeze(-1), time_values=time_values
        ).logits

        assert from_3d.shape == (BATCH, 1, 1)
        assert torch.allclose(from_2d, from_3d, atol=1e-6)

    def test_inputs_embeds_can_replace_input_ids(self):
        model = _model()
        _, time_values = _inputs()
        inputs_embeds = torch.randn(BATCH, SEQ, HIDDEN_SIZE)

        output = model(inputs_embeds=inputs_embeds, time_values=time_values)

        assert output.logits.shape == (BATCH, 1, 1)
        assert torch.isfinite(output.logits).all()

    def test_multivariate_input_size_is_reflected_in_logits(self):
        model = _model(input_size=3)
        _, time_values = _inputs()
        input_ids = torch.randn(BATCH, SEQ, 3)

        output = model(input_ids=input_ids, time_values=time_values)

        assert output.logits.shape == (BATCH, 1, 3)

    def test_output_flags_forwarded_to_model(self):
        model = _model()

        output = model(
            *_inputs(),
            output_hidden_states=True,
            output_attentions=True,
        )

        assert output.hidden_states is not None
        assert len(output.hidden_states) == NUM_LAYERS + 1
        assert output.hidden_states[-1].shape == (BATCH, SEQ, HIDDEN_SIZE)
        assert output.attentions is not None
        assert len(output.attentions) == NUM_LAYERS
        assert output.attentions[0].shape == (BATCH, NUM_HEADS, SEQ, SEQ)

    def test_config_flags_used_when_arguments_are_none(self):
        model = _model(output_attentions=True, output_hidden_states=True)

        output = model(*_inputs())

        assert output.hidden_states is not None
        assert output.attentions is not None

    def test_use_cache_flag_is_passed_to_model(self):
        model = _model()

        with_cache = model(*_inputs())
        # ``use_cache=None`` falls back to ``config.use_cache`` (True here)
        explicit_cache = model(*_inputs(), use_cache=True)

        assert with_cache.past_key_values is not None
        assert explicit_cache.past_key_values is not None

    def test_horizon_lengths_are_forced_to_single_step(self):
        model = _model(horizon_lengths=[4])

        output = model(*_inputs())

        assert model.config.horizon_lengths == [1]
        assert len(model.lm_heads) == 1
        assert model.horizon_length_map == {1: 0}
        assert output.logits.shape == (BATCH, 1, 1)


class TestForwardReturnDict:
    """``return_dict`` controls the returned container."""

    def test_tuple_output_contains_logits_cache_and_router_logits(self):
        model = _model()

        output = model(*_inputs(), return_dict=False)

        assert isinstance(output, tuple)
        assert len(output) == 3
        logits, cache, router_logits = output
        assert isinstance(logits, torch.Tensor)
        assert logits.shape == (BATCH, 1, 1)
        assert cache is not None
        assert isinstance(router_logits, tuple)
        assert len(router_logits) == NUM_LAYERS
        assert router_logits[0].shape == (BATCH * SEQ, 4)

    def test_tuple_output_with_labels_prepends_losses(self):
        model = _model()
        input_ids, time_values = _inputs()
        labels = torch.randn(BATCH, 1)

        output = model(
            input_ids=input_ids,
            time_values=time_values,
            labels=labels,
            return_dict=False,
        )

        assert isinstance(output, tuple)
        assert len(output) == 5
        loss, aux_loss, logits = output[0], output[1], output[2]
        assert isinstance(loss, torch.Tensor)
        assert loss.dim() == 0
        assert torch.isfinite(loss)
        assert aux_loss is None
        assert logits.shape == (BATCH, 1, 1)


class TestForwardLoss:
    """Supervised / autoregressive loss computation."""

    def test_labels_yield_finite_scalar_loss_with_gradients(self):
        model = _model()
        input_ids, time_values = _inputs()
        labels = torch.randn(BATCH, 1)

        output = model(input_ids=input_ids, time_values=time_values, labels=labels)

        assert output.loss is not None
        assert output.loss.dim() == 0
        assert torch.isfinite(output.loss)
        assert output.loss.item() > 0.0
        assert output.loss.requires_grad
        assert output.logits.shape == (BATCH, 1, 1)

        output.loss.backward()
        head_grad = model.lm_heads[0].out_layer.weight.grad
        assert head_grad is not None
        assert torch.isfinite(head_grad).all()

    def test_loss_is_independent_of_batched_label_duplication(self):
        """Repeating the same label for every batch element keeps the mean loss."""
        model = _model()
        input_ids, time_values = _inputs(batch=1, seq=SEQ)
        single_label = torch.full((1, 1), 0.5)
        doubled_label = torch.full((2, 1), 0.5)

        single = model(
            input_ids=input_ids.clone(),
            time_values=time_values.clone(),
            labels=single_label,
            return_dict=False,
        )[0]
        doubled = model(
            input_ids=torch.cat([input_ids.clone(), input_ids.clone()], dim=0),
            time_values=torch.cat([time_values.clone(), time_values.clone()], dim=0),
            labels=doubled_label,
            return_dict=False,
        )[0]

        assert torch.isclose(single, doubled, atol=1e-5)

    def test_loss_masks_change_the_reported_loss(self):
        model = _model()
        input_ids, time_values = _inputs()
        labels = torch.randn(BATCH, 1)

        unmasked = model(
            input_ids=input_ids.clone(), time_values=time_values, labels=labels.clone()
        ).loss
        masked = model(
            input_ids=input_ids.clone(),
            time_values=time_values,
            labels=labels.clone(),
            loss_masks=torch.tensor([[1.0], [0.0]]),
        ).loss

        assert torch.isfinite(unmasked)
        assert torch.isfinite(masked)
        assert not torch.isclose(unmasked, masked, atol=1e-5)

    def test_labels_and_padded_attention_mask_still_produce_a_loss(self):
        model = _model()
        input_ids, time_values = _inputs()
        labels = torch.randn(BATCH, 1)
        attention_mask = torch.tensor([[1, 1, 1, 0, 0], [1, 1, 1, 0, 0]])

        output = model(
            input_ids=input_ids,
            time_values=time_values,
            attention_mask=attention_mask,
            labels=labels,
        )

        assert torch.isfinite(output.loss)
        assert output.loss.requires_grad

    @pytest.mark.parametrize("aux_factor", [0.0, 0.02, 0.5])
    def test_router_aux_loss_is_added_to_the_ar_loss(self, monkeypatch, aux_factor):
        model = _model(router_aux_loss_factor=aux_factor)
        input_ids, time_values = _inputs()
        labels = torch.randn(BATCH, 1)
        attention_mask = torch.ones(BATCH, SEQ)
        captured = {}

        def fake_load_balancing_loss_func(
            gate_logits, top_k, num_experts=None, attention_mask=None
        ):
            captured["gate_logits"] = gate_logits
            captured["top_k"] = top_k
            captured["num_experts"] = num_experts
            captured["attention_mask"] = attention_mask
            return torch.tensor(2.0)

        monkeypatch.setattr(
            modeling_mira, "load_balancing_loss_func", fake_load_balancing_loss_func
        )
        monkeypatch.setattr(
            MIRAForPrediction,
            "calc_ar_loss",
            lambda self, predictions, labels, loss_masks, horizon_length: torch.tensor(
                1.5
            ),
        )

        output = model(
            input_ids=input_ids,
            time_values=time_values,
            attention_mask=attention_mask,
            labels=labels,
        )

        expected = 1.5 + aux_factor * 2.0
        assert torch.isclose(output.loss, torch.tensor(expected), atol=1e-6)
        assert captured["top_k"] == model.num_experts_per_tok
        assert captured["num_experts"] == model.config.num_experts
        assert isinstance(captured["gate_logits"], (tuple, list))
        assert len(captured["gate_logits"]) == NUM_LAYERS
        assert captured["attention_mask"] is attention_mask

    def test_router_aux_loss_not_computed_when_apply_aux_loss_is_disabled(
        self, monkeypatch
    ):
        model = _model(use_dense=True, apply_aux_loss=False)
        input_ids, time_values = _inputs()
        labels = torch.randn(BATCH, 1)

        def fail_if_called(*args, **kwargs):  # pragma: no cover - guard only
            raise AssertionError("load_balancing_loss_func must not be used")

        monkeypatch.setattr(
            modeling_mira, "load_balancing_loss_func", fail_if_called
        )

        output = model(input_ids=input_ids, time_values=time_values, labels=labels)

        assert model.apply_aux_loss is False
        assert output.loss is not None
        assert torch.isfinite(output.loss)
        assert output.loss.requires_grad

    def test_calc_ar_loss_is_called_once_per_lm_head(self, monkeypatch):
        model = _model()
        input_ids, time_values = _inputs()
        labels = torch.randn(BATCH, 1)
        seen = []

        def fake_calc_ar_loss(self, predictions, labels, loss_masks, horizon_length):
            seen.append((predictions.shape, horizon_length))
            return torch.tensor(1.0)

        monkeypatch.setattr(MIRAForPrediction, "calc_ar_loss", fake_calc_ar_loss)
        monkeypatch.setattr(
            modeling_mira,
            "load_balancing_loss_func",
            lambda *args, **kwargs: torch.tensor(0.0),
        )

        output = model(input_ids=input_ids, time_values=time_values, labels=labels)

        assert len(seen) == len(model.config.horizon_lengths) == 1
        prediction_shape, horizon_length = seen[0]
        assert prediction_shape == (BATCH, 1, 1)
        assert horizon_length == 1
        assert torch.isclose(output.loss, torch.tensor(1.0), atol=1e-6)


class TestForwardMaxHorizonLength:
    """``max_horizon_length`` truncation logic (labels-free branch)."""

    def test_default_max_horizon_length_uses_first_config_horizon(self):
        model = _model()

        output = model(*_inputs())

        assert output.logits.shape == (BATCH, 1, 1)

    @pytest.mark.parametrize("max_horizon_length", [1, 3, 10])
    def test_max_horizon_length_at_least_horizon_does_not_truncate(
        self, max_horizon_length
    ):
        model = _model()

        output = model(*_inputs(), max_horizon_length=max_horizon_length)

        assert output.logits.shape == (BATCH, 1, 1)

    def test_max_horizon_length_zero_truncates_logits_to_empty(self):
        model = _model()

        output = model(*_inputs(), max_horizon_length=0)

        assert output.logits.shape == (BATCH, 1, 0)

    def test_multivariate_truncation_size_uses_input_size(self):
        model = _model(input_size=3)
        _, time_values = _inputs()
        input_ids = torch.randn(BATCH, SEQ, 3)

        output = model(
            input_ids=input_ids, time_values=time_values, max_horizon_length=2
        )

        assert output.logits.shape == (BATCH, 1, 3)


class TestForwardODE:
    """Terminal ODE extrapolation branch of ``forward``."""

    @staticmethod
    def _model_with_recorder(
        training=False, use_terminal_ode=True, offset=1.5, **overrides
    ):
        model = _model(
            training=training, use_terminal_ode=use_terminal_ode, **overrides
        )
        # trusted even if torchdiffeq is unavailable: the block is replaced anyway
        model.use_terminal_ode = use_terminal_ode
        recorder = _RecordingODEBlock(offset=offset)
        model.ode_extrapolation_block = recorder
        return model, recorder

    def test_ode_block_receives_last_time_and_hidden_state(self):
        model, recorder = self._model_with_recorder(offset=None)
        input_ids, time_values = _inputs()
        next_target = torch.tensor([8.0, 9.0])

        output = model(
            input_ids=input_ids,
            time_values=time_values,
            next_target_time_values=next_target,
        )

        assert len(recorder.calls) == 1
        h_N, t_N, t_Nplus1 = recorder.calls[0]
        assert h_N.shape == (BATCH, HIDDEN_SIZE)
        assert torch.equal(t_N, time_values[:, -1])
        assert torch.equal(t_Nplus1, next_target)
        # the ODE output (not the raw last hidden state) feeds the lm head
        expected_logits = model.lm_heads[0](h_N.unsqueeze(1))
        assert torch.allclose(output.logits, expected_logits, atol=1e-6)

    def test_ode_output_is_used_downstream(self):
        model, recorder = self._model_with_recorder()
        input_ids, time_values = _inputs()
        next_target = torch.tensor([8.0, 9.0])

        with_ode = model(
            input_ids=input_ids.clone(),
            time_values=time_values,
            next_target_time_values=next_target,
        ).logits
        without_ode = model(input_ids=input_ids.clone(), time_values=time_values).logits

        h_N = recorder.calls[0][0]
        expected = model.lm_heads[0]((h_N + 1.5).unsqueeze(1))
        assert torch.allclose(with_ode, expected, atol=1e-6)
        assert not torch.allclose(with_ode, without_ode, atol=1e-6)

    def test_identity_ode_block_reproduces_no_ode_logits(self):
        model, _ = self._model_with_recorder()
        model.ode_extrapolation_block = _RecordingODEBlock(offset=0.0)
        input_ids, time_values = _inputs()

        baseline = model(input_ids=input_ids.clone(), time_values=time_values).logits
        ode_out = model(
            input_ids=input_ids.clone(),
            time_values=time_values,
            next_target_time_values=torch.tensor([8.0, 9.0]),
        ).logits

        assert torch.allclose(baseline, ode_out, atol=1e-6)

    @pytest.mark.parametrize(
        "next_target",
        [
            torch.tensor([8.0, 9.0]),
            torch.tensor([[8.0], [9.0]]),
        ],
        ids=["one_dim", "two_dim"],
    )
    def test_next_target_time_values_shapes_are_normalised(self, next_target):
        model, recorder = self._model_with_recorder(offset=None)
        input_ids, time_values = _inputs()

        model(
            input_ids=input_ids,
            time_values=time_values,
            next_target_time_values=next_target,
        )

        _, t_N, t_Nplus1 = recorder.calls[0]
        assert t_N.shape == (BATCH,)
        assert t_Nplus1.shape == (BATCH,)
        assert torch.equal(t_Nplus1, next_target.reshape(-1))

    def test_scalar_next_target_time_values_is_broadcast_over_batch(self):
        model, recorder = self._model_with_recorder(offset=None)
        input_ids, time_values = _inputs()

        model(
            input_ids=input_ids,
            time_values=time_values,
            next_target_time_values=torch.tensor(7.0),
        )

        _, _, t_Nplus1 = recorder.calls[0]
        assert t_Nplus1.shape == (BATCH,)
        assert torch.equal(t_Nplus1, torch.full((BATCH,), 7.0))

    def test_ode_block_skipped_when_use_terminal_ode_is_false(self):
        model, recorder = self._model_with_recorder(use_terminal_ode=False)
        input_ids, time_values = _inputs()

        output = model(
            input_ids=input_ids.clone(),
            time_values=time_values,
            next_target_time_values=torch.tensor([8.0, 9.0]),
        )

        assert recorder.calls == []
        baseline = model(input_ids=input_ids.clone(), time_values=time_values).logits
        assert torch.allclose(output.logits, baseline, atol=1e-6)

    def test_ode_block_skipped_when_block_is_none(self):
        model = _model()
        model.use_terminal_ode = True
        model.ode_extrapolation_block = None
        input_ids, time_values = _inputs()

        output = model(
            input_ids=input_ids.clone(),
            time_values=time_values,
            next_target_time_values=torch.tensor([8.0, 9.0]),
        )

        assert output.logits.shape == (BATCH, 1, 1)

    def test_ode_branch_supports_losses_and_backpropagation(self):
        model, recorder = self._model_with_recorder(offset=None)
        input_ids, time_values = _inputs()
        labels = torch.randn(BATCH, 1)

        output = model(
            input_ids=input_ids,
            time_values=time_values,
            next_target_time_values=torch.tensor([8.0, 9.0]),
            labels=labels,
        )

        assert torch.isfinite(output.loss)
        output.loss.backward()
        assert recorder.scale.grad is not None
        assert torch.isfinite(recorder.scale.grad).all()

    def test_warns_when_training_without_next_target_time_values(self):
        model = _model(training=True, use_terminal_ode=True)
        input_ids, time_values = _inputs()

        with pytest.warns(UserWarning, match=ODE_SKIPPED_MSG):
            output = model(input_ids=input_ids, time_values=time_values)

        assert output.logits.shape == (BATCH, 1, 1)

    def test_does_not_warn_in_eval_mode_without_next_target_time_values(self):
        model = _model(training=False, use_terminal_ode=True)
        input_ids, time_values = _inputs()

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            output = model(input_ids=input_ids, time_values=time_values)

        messages = [str(w.message) for w in recorded]
        assert not any(ODE_SKIPPED_MSG in msg for msg in messages)
        assert output.logits.shape == (BATCH, 1, 1)

    def test_does_not_warn_in_training_when_next_target_time_values_given(self):
        model, recorder = self._model_with_recorder(training=True)
        input_ids, time_values = _inputs()

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            output = model(
                input_ids=input_ids,
                time_values=time_values,
                next_target_time_values=torch.tensor([8.0, 9.0]),
            )

        messages = [str(w.message) for w in recorded]
        assert not any(ODE_SKIPPED_MSG in msg for msg in messages)
        assert len(recorder.calls) == 1
        assert output.logits.shape == (BATCH, 1, 1)


class TestForwardWithRealODEBlock:
    """End-to-end checks against the production ``TerminalODEBlock``."""

    @staticmethod
    def _model_with_real_ode(**overrides):
        pytest.importorskip("torchdiffeq")
        if not modeling_mira.is_torchdiffeq_available:
            pytest.skip("torchdiffeq is not available")
        model = _model(use_terminal_ode=True, **overrides)
        if not model.use_terminal_ode or model.ode_extrapolation_block is None:
            pytest.skip("terminal ODE block could not be constructed")
        return model

    def test_real_ode_block_changes_logits(self):
        model = self._model_with_real_ode()
        input_ids, time_values = _inputs()
        next_target = torch.tensor([8.0, 9.0])

        baseline = model(input_ids=input_ids.clone(), time_values=time_values).logits
        ode_logits = model(
            input_ids=input_ids.clone(),
            time_values=time_values,
            next_target_time_values=next_target,
        ).logits

        assert ode_logits.shape == (BATCH, 1, 1)
        assert torch.isfinite(ode_logits).all()
        assert not torch.allclose(ode_logits, baseline, atol=1e-6)

    def test_real_ode_block_returns_initial_state_for_non_positive_interval(self):
        model = self._model_with_real_ode()
        input_ids, time_values = _inputs()
        same_time = time_values[:, -1].clone()

        baseline = model(input_ids=input_ids.clone(), time_values=time_values).logits
        with pytest.warns(UserWarning, match="delta_t"):
            ode_logits = model(
                input_ids=input_ids.clone(),
                time_values=time_values,
                next_target_time_values=same_time,
            ).logits

        assert torch.allclose(ode_logits, baseline, atol=1e-6)


class TestForwardInputValidation:
    """Invalid argument combinations raise the decoder's errors."""

    def test_raises_when_both_input_ids_and_inputs_embeds_given(self):
        model = _model()
        input_ids, time_values = _inputs()

        with pytest.raises(ValueError, match="both decoder_input_ids"):
            model(
                input_ids=input_ids,
                inputs_embeds=torch.randn(BATCH, SEQ, HIDDEN_SIZE),
                time_values=time_values,
            )

    def test_raises_when_no_input_given(self):
        model = _model()
        _, time_values = _inputs()

        with pytest.raises(ValueError, match="You have to specify either"):
            model(time_values=time_values)

    def test_raises_when_time_values_missing(self):
        model = _model()
        input_ids, _ = _inputs()

        with pytest.raises(ValueError, match="time_values"):
            model(input_ids=input_ids)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))