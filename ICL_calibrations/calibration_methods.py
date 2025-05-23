from ICL_modules import s_random, functions
import itertools
import numpy as np
import pandas as pd
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import functools
import random
import copy
from scipy.optimize import minimize
from collections import defaultdict

class calibration():
    def __init__(self) -> None:
        pass

    def train(self) -> None:
        pass

    def inference(self, label_space_prob, full_vocab_prob, hidden_state) -> list[float]:
        pass

    def __call__(self, label_space_prob, full_vocab_prob, hidden_state) -> list[float]:
        return self.inference(label_space_prob, full_vocab_prob, hidden_state)

class domain_calibration(calibration):
    def __init__(self, label_space) -> None:
        self.label_space = label_space
        n_label = len(label_space)
        self.n_label = n_label
        self.calibrationA = [1e-5] * n_label

    def get_domain_sample(self, demonstration_set, sample_length):
        random = s_random.Random()
        while True:
            ret = []
            for i in range(len(demonstration_set[0][0])):
                output = []
                while len(output) < sample_length:
                    random_sample = demonstration_set[random.get_int_from_range(0, len(demonstration_set) - 1)][0][i]
                    random_sample = random_sample.split(' ')
                    if len(random_sample) > 1:
                        
                        random_index = random.get_int_from_range(0, len(random_sample) - 1)  # random.get_int_from_range(0,len(random_sample)-1)
                        output.append(random_sample[random_index]) # If random_sample has only one element or is empty, append the element if it exists or skip
                    elif len(random_sample) == 1:
                        output.append(random_sample[0])
                    
                    # random_index = random.get_int_from_range(0, len(random_sample) - 1)
                    # output.append(random_sample[random_index])
                output = ' '.join(output)
                ret.append(output)
            yield ret

    def train(
        self,
        default_prompt_maker: callable, # input: demos_lines: <list[(list[str], str)]>, query_line: <list[str]> return: prompt, recommendation: prompt_writter.write_prompt_from_dataline
        feedforward: callable, # feedforward function, input: prompt: <str> return: label_space_prob
        demonstration_set = None,
        calibration_number = 20,
        sample_length = 64,
        k = 4,
        demonstration_set_index = None
    ) -> None:
        
        demonstration_samples = demonstration_set_index
        
        gen = self.get_domain_sample(demonstration_set, sample_length)
        for i in range(calibration_number):
            print("\r", end="")
            print("Process: {}%, {} in {}".format(
                int((i + 1) / calibration_number * 100),
                (i + 1),
                calibration_number
            ), ">>" * int((i + 1) / calibration_number * 32), end="")
            random_sentence = next(gen)

            prompt = default_prompt_maker([demonstration_set[demonstration_samples[j]] for j in range(k)], random_sentence)
            label_space_prob = feedforward(prompt = prompt, label_space = self.label_space)
            self.calibrationA = [self.calibrationA[j] + label_space_prob[j] for j in range(self.n_label)]
        self.calibrationA = [self.calibrationA[j] / calibration_number for j in range(self.n_label)]
        print("\nCalibration Training Finished.\n")

    def inference(self, label_space_prob, full_vocab_prob, hidden_state) -> list[float]:
        total = sum(label_space_prob[j] / self.calibrationA[j] for j in range(self.n_label))
        return [(label_space_prob[j] / self.calibrationA[j])/total for j in range(self.n_label)]  #functions.softmax([label_space_prob[j] / self.calibrationA[j] for j in range(self.n_label)])

class contextual_calibration(calibration):

    def __init__(self, label_space) -> None:
        self.label_space = label_space
        n_label = len(label_space)
        self.n_label = n_label
        self.calibrationA = [1e-5] * n_label

    def train(
        self,
        default_prompt_maker: callable, 
        feedforward: callable, 
        demonstration_set = None,
        k = 4,
        demonstration_set_index = None
    ) -> None:
        if demonstration_set_index is not None:
          demonstration_samples = demonstration_set_index
        else:
          my_random = stable_random.stable_random()
          demonstration_samples = my_random.sample_index_set(k, len(demonstration_set), allow_repetition=False)
        print(demonstration_samples)

        content_free = [[''],['NA'],['[MASK]']]
        for i, cf in enumerate(content_free):
            print("\r", end="")
            print("Process: {}%, {} in {}".format(
                int((i + 1) / len(content_free) * 100),
                (i + 1),
                len(content_free)
            ), ">>" * int((i + 1) / len(content_free) * 32), end="")
            prompt = default_prompt_maker([demonstration_set[demonstration_samples[j]] for j in range(k)], cf)
            label_space_prob = feedforward(prompt = prompt, label_space = self.label_space)
            self.calibrationA = [self.calibrationA[j] + label_space_prob[j] for j in range(self.n_label)]
        self.calibrationA = [self.calibrationA[j] / len(content_free) for j in range(self.n_label)]
        print("\nCalibration Training Finished.\n")

    def inference(self, label_space_prob, full_vocab_prob, hidden_state) -> list[float]:
        return functions.softmax([label_space_prob[j] / self.calibrationA[j] for j in range(self.n_label)])




def batch_calibration(
    label_space_probs: list[list[float]], 
    batch_size = 128, 
) -> list[list[float]]:
    ret = []
    step = len(label_space_probs) // batch_size
    for i in range(step):
        batch = label_space_probs[i * batch_size: (i + 1) * batch_size]
        mean_bias = [0] * len(batch[0])
        for j in range(batch_size):
            for k in range(len(batch[j])):
                mean_bias[k] += batch[j][k]
        mean_bias = [x / batch_size for x in mean_bias]
        for j in range(batch_size):
            ret.append(functions.softmax([batch[j][k] - mean_bias[k] for k in range(len(batch[j]))]))
    last_batch = label_space_probs[step * batch_size:]
    if len(last_batch) == 0:
        return ret
    mean_bias = [0] * len(last_batch[0])
    for j in range(len(last_batch)):
        for k in range(len(last_batch[j])):
            mean_bias[k] += last_batch[j][k]
    mean_bias = [x / len(last_batch) for x in mean_bias]
    for j in range(len(last_batch)):
        ret.append(functions.softmax([last_batch[j][k] - mean_bias[k] for k in range(len(last_batch[j]))]))
    return ret

###########################################

class lr_calib_scipy_1d_cos(calibration):
    """
    This class implements an independent (univariate) calibration for each non-reference class.
    
    For a prediction with original probabilities [P(y=0|x), P(y=1|x), ..., P(y=n_label-1|x)],
    the features are computed as:
        x_c = log(P(y=c|x)/P(y=0|x)) for c = 1,...,n_label-1.
    
    The calibration equations are:
        log(P*(y=c|x)/P*(y=0|x)) = b_c + w_c * x_c, for c = 1,..., n_label-1,
    with the reference class fixed:
        logit_0 = 0.
    
    The calibrated probabilities are then given by:
        P*(y=0|x) = 1 / (1 + sum_{c=1}^{n_label-1} exp(b_c + w_c * x_c))
        P*(y=c|x) = exp(b_c + w_c * x_c) / (1 + sum_{j=1}^{n_label-1} exp(b_j + w_j * x_j)).
    
    A constraint is imposed on the calibration parameters: for each non-reference class c,
    we require the cosine similarity between [b_c, w_c] and [0, 1] (i.e. w_c/√(b_c²+w_c²)) to be high.
    Specifically, we require:
    
        (1/(n_label-1)) * sum_{c=1}^{n_label-1} (w_c / √(b_c²+w_c²)) >= cosine_threshold.
    """
    
    def __init__(
        self,
        label_space,
        use_invariance=True,
        lambda_invariance=1.0,
        invariance_loss_type='sym_ce',
        constraint=False,
        max_iter=100,
        verbose=False,
        k=None,
        dic=None,
        cosine_threshold=0.9  # minimum average cosine similarity required
    ):
        super().__init__()
        self.label_space = label_space
        self.n_label = len(label_space)
        self.use_invariance = use_invariance
        self.lambda_invariance = lambda_invariance
        self.invariance_loss_type = invariance_loss_type
        self.constraint = constraint
        self.max_iter = max_iter
        self.verbose = verbose
        
        # Additional parameters
        self.k = k
        self.dic = dic
        self.cosine_threshold = cosine_threshold
        
        # Final learned parameters.
        # We only optimize for non-reference classes (classes 1,..., n_label-1).
        # For each such class we have 2 parameters: [b_c, w_c].
        # Total parameters = (n_label - 1) * 2.
        self.params_ = None
        self.fitted_ = False

    # -------------------------------------------------------------------------
    # Feature building:
    # For a given probability vector, compute x = [log(P(y=1)/P(y=0)), ..., log(P(y=n_label-1)/P(y=0))]
    # -------------------------------------------------------------------------
    def _make_features(self, prob_vector):
        eps = 1e-9
        base = prob_vector[0] + eps
        feats = []
        for c in range(1, self.n_label):
            feats.append(np.log(prob_vector[c] / base))
        return np.array(feats, dtype=float)  # shape: (n_label-1,)

    # -------------------------------------------------------------------------
    # Unpack parameters:
    # The optimized parameters (a 1D array of length (n_label-1)*2) are reshaped into a matrix.
    # Row c (for c=1,..., n_label-1) contains [b_c, w_c].
    # For the reference class (class 0) we set parameters to zeros.
    # -------------------------------------------------------------------------
    def _unpack_params(self, params):
        non_ref = params.reshape(self.n_label - 1, 2)  # shape: (n_label-1, 2)
        ref = np.zeros((1, 2))
        param_matrix = np.vstack([ref, non_ref])
        return param_matrix  # shape: (n_label, 2)

    # -------------------------------------------------------------------------
    # Compute logits:
    # For each sample with feature vector x (length n_label-1),
    # the logit for class 0 is 0, and for class c (c>=1):
    # logit_c = b_c + w_c * x[c-1]
    # -------------------------------------------------------------------------
    def _compute_logits(self, param_matrix, x):
        logits = [0.0]  # class 0
        for c in range(1, self.n_label):
            b_c = param_matrix[c, 0]
            w_c = param_matrix[c, 1]
            logits.append(b_c + w_c * x[c - 1])
        return np.array(logits)

    # -------------------------------------------------------------------------
    # Negative Log-Likelihood (using softmax)
    # -------------------------------------------------------------------------
    def _negative_log_likelihood(self, params, X, Y):
        param_matrix = self._unpack_params(params)
        eps = 1e-9
        N = len(X)
        ll = 0.0
        for i in range(N):
            logits_i = self._compute_logits(param_matrix, X[i])
            shift = logits_i - np.max(logits_i)
            exps = np.exp(shift)
            sumExps = np.sum(exps)
            prob = exps / (sumExps + eps)
            y_i = int(Y[i])
            ll -= np.log(prob[y_i] + eps)
        return ll

    # -------------------------------------------------------------------------
    # Invariance penalty (as in previous models)
    # -------------------------------------------------------------------------
    def _invariance_penalty(self, params, X, pairs):
        param_matrix = self._unpack_params(params)
        eps = 1e-9
        N = len(X)
        all_probs = []
        for i in range(N):
            logits_i = self._compute_logits(param_matrix, X[i])
            shift = logits_i - np.max(logits_i)
            exps = np.exp(shift)
            sumExps = np.sum(exps)
            p_i = exps / (sumExps + eps)
            all_probs.append(p_i)
        total_pen = 0.0
        for (i, j) in pairs:
            p_i = all_probs[i]
            p_j = all_probs[j]
            if self.invariance_loss_type == 'mse':
                total_pen += np.sum((p_i - p_j) ** 2)
            elif self.invariance_loss_type == 'l1':
                total_pen += np.sum(np.abs(p_i - p_j))
            elif self.invariance_loss_type == 'sym_ce':
                ce_ij = -np.sum(p_j * np.log(p_i + eps))
                ce_ji = -np.sum(p_i * np.log(p_j + eps))
                total_pen += (ce_ij + ce_ji)
            else:
                total_pen += np.sum((p_i - p_j) ** 2)
        return total_pen

    # -------------------------------------------------------------------------
    # Full objective: NLL + lambda_invariance * invariance penalty
    # -------------------------------------------------------------------------
    def _objective(self, params, X, Y, pairs):
        nll = self._negative_log_likelihood(params, X, Y)
        if self.use_invariance and len(pairs) > 0:
            pen = self._invariance_penalty(params, X, pairs)
        else:
            pen = 0.0
        return nll + self.lambda_invariance * pen

    # -------------------------------------------------------------------------
    # Training
    # -------------------------------------------------------------------------
    def train(
        self,
        default_prompt_maker: callable,
        feedforward: callable,
        demonstration_set=None,
        k=4,
        demonstration_set_index=None
    ):
        print(demonstration_set_index)
        train_indexes = self._permutate(demonstration_set_index, k)

        probs_list = []
        labels_list = []
        queries_list = []

        total = len(train_indexes)
        for i, ind in enumerate(train_indexes):
            print(
                f"\rProcess: {int((i + 1) / total * 100)}% " +
                f"[{'>>' * int((i + 1) / total * 32)}" +
                f"{'.' * (32 - int((i + 1) / total * 32))}] " +
                f"{i+1}/{total}",
                end="", flush=True
            )
            demonstration_samples = ind[:k]
            query_sample = ind[k]
            query = demonstration_set[query_sample][0]
            label = demonstration_set.get_label(query_sample)
            prompt = default_prompt_maker(
                [demonstration_set[demonstration_samples[j]] for j in range(k)],
                query
            )
            label_space_probs = feedforward(prompt=prompt, label_space=self.label_space)
            probs_list.append(label_space_probs)
            labels_list.append(label)
            queries_list.append(query_sample)
        print()

        # Build features and labels.
        X_list = []
        y_list = []
        for pr, lab in zip(probs_list, labels_list):
            x_vec = self._make_features(pr)  # shape: (n_label-1,)
            X_list.append(x_vec)
            y_list.append(self.label_space.index(lab))
        X = np.array(X_list, dtype=float)
        Y = np.array(y_list, dtype=float)
        N = len(X)

        df = pd.DataFrame({
            "label": Y,
            "query_index": queries_list,
            "features": list(X_list)
        })

        # Build pairs for invariance penalty.
        query_map = defaultdict(list)
        for i, qid in enumerate(df["query_index"]):
            query_map[qid].append(i)
        pairs = []
        for qid, idxs in query_map.items():
            if len(idxs) < 2:
                continue
            for i1 in range(len(idxs)):
                for i2 in range(i1 + 1, len(idxs)):
                    pairs.append((idxs[i1], idxs[i2]))

        # Prepare initial parameters: shape = ((n_label-1)*2,)
        n_dim = 1  # each non-reference calibrator is univariate.
        init_params = np.zeros((self.n_label - 1) * 2, dtype=float)

        def func_to_minimize(params):
            return self._objective(params, X, Y, pairs)

        # -------------------------------
        # BUILD CONSTRAINTS (cosine similarity constraint)
        # -------------------------------
        constraints_list = []
        if self.constraint:
            def cosine_constraint(params):
                # Unpack: each non-reference class c has parameters [b_c, w_c]
                non_ref = params.reshape(self.n_label - 1, 2)
                cosine_sum = 0.0
                for c in range(self.n_label - 1):
                    b_c, w_c = non_ref[c]
                    norm = np.sqrt(b_c**2 + w_c**2)
                    if norm < 1e-9:
                        cosine = 0.0
                    else:
                        cosine = w_c / norm  # cosine similarity with [0,1]
                    cosine_sum += cosine
                avg_cosine = cosine_sum / (self.n_label - 1)
                return avg_cosine - self.cosine_threshold
            constraints_list.append({'type': 'ineq', 'fun': cosine_constraint})
            solver_method = 'trust-constr'
        else:
            solver_method = 'BFGS'

        # -------------------------------
        # Run optimization.
        # -------------------------------
        print('Optimization started...')
        res = minimize(
            func_to_minimize,
            init_params,
            method=solver_method,
            constraints=constraints_list,
            options={'maxiter': self.max_iter, 'disp': self.verbose}
        )

        self.params_ = res.x
        self.fitted_ = True

        if self.verbose:
            print("\n[SCIPY] Optimization success:", res.success)
            print("[SCIPY] Message:", res.message)

        # Compute predictions on the training set.
        param_matrix = self._unpack_params(self.params_)
        all_probs = []
        for i in range(N):
            logits_i = self._compute_logits(param_matrix, X[i])
            shift = logits_i - np.max(logits_i)
            exps = np.exp(shift)
            sumExps = np.sum(exps)
            p_i = exps / (sumExps + 1e-9)
            all_probs.append(p_i)
        for c in range(self.n_label):
            df[f"score_{c}"] = [p[c] for p in all_probs]
        df["predicted"] = [np.argmax(p) for p in all_probs]

        print("\n[SCIPY] Calibration Training Finished.\n")
        return df

    # -------------------------------------------------------------------------
    # Inference
    # -------------------------------------------------------------------------
    def inference(self, label_space_prob, full_vocab_prob, hidden_state):
        if not self.fitted_:
            raise RuntimeError("lr_calib_scipy model not fitted yet.")
        x = self._make_features(label_space_prob)
        param_matrix = self._unpack_params(self.params_)
        logits = self._compute_logits(param_matrix, x)
        shift = logits - np.max(logits)
        exps = np.exp(shift)
        sumExps = np.sum(exps)
        final_probs = exps / (sumExps + 1e-9)
        return final_probs.tolist()

    def __call__(self, label_space_prob, full_vocab_prob, hidden_state):
        return self.inference(label_space_prob, full_vocab_prob, hidden_state)

    # -------------------------------------------------------------------------
    # Permutation helper
    # -------------------------------------------------------------------------
    def _permutate(self, elements, k):
        if k == 0:
            return [list(perm) for perm in itertools.permutations(elements, r=1)]
        else:
            extended_permutations = [
                list(base_perm + (extra_elem,))
                for base_perm in itertools.permutations(elements, r=k)
                for extra_elem in elements if extra_elem not in base_perm
            ]
            return extended_permutations    
    ##############




class lr_calib_scipy_1d_cos_hinge(calibration):
    """
    Logistic-regression calibration with a *one-sided* soft angular penalty.

    For each non-reference class c (1 … J-1) we keep the angle
    α_c = arccos( w_c / ||(b_c, w_c)|| ) ≤ θ_max.
    A hinge loss is added whenever α_c exceeds θ_max:

        φ_c(θ) = max(0,  cos θ_max − cos α_c )

    The per-class φ_c are aggregated either as an *average* (default) or
    as a *sum*, controlled by `penalty_on`.

    Because the penalty is soft, the optimisation is unconstrained and
    solved with BFGS.
    Parameters
    ----------
    fix_unit_weights : bool, default False         <<< NEW / CHANGED >>>
        If True, all non‑reference weights w_c are fixed to 1 and only
        the biases b_c are learnt.
    """

    # -----------------------------------------------------------------
    # Initialiser
    # -----------------------------------------------------------------
    def __init__(
        self,
        label_space,
        # invariance ---------------------------------------------------
        use_invariance=True,
        lambda_invariance=1.0,
        invariance_loss_type="sym_ce",
        # soft upper‑angle penalty ------------------------------------
        use_upper_soft_angle=True,
        lambda_angle=1.0,
        max_angle_deg=60.0,         # θ_max (0 < θ_max ≤ 180)
        penalty_on="average",       # "average" | "per_class"
        # optimisation / misc -----------------------------------------
        max_iter=100,
        verbose=False,
        epsilon=1e-9,
        # <<< NEW / CHANGED -------------------------------------------
        fix_unit_weights: bool = False,
        # legacy flags -------------------------------------------------
        constraint=False,
        cosine_threshold=0.9,
        k=None,
        dic=None,
    ):
        super().__init__()

        # ---------------- core settings ------------------------------
        self.label_space = label_space
        self.n_label = len(label_space)

        self.use_invariance = use_invariance
        self.lambda_invariance = lambda_invariance
        self.invariance_loss_type = invariance_loss_type

        self.use_upper_soft_angle = use_upper_soft_angle
        self.lambda_angle = lambda_angle
        self.max_angle_deg = float(max_angle_deg)
        self.penalty_on = penalty_on.lower()
        if not (0.0 < self.max_angle_deg <= 180.0):
            raise ValueError("Require 0 < max_angle_deg ≤ 180")
        self._cos_up = np.cos(np.deg2rad(self.max_angle_deg))

        self.max_iter = max_iter
        self.verbose = verbose
        self.epsilon = epsilon

        # <<< NEW / CHANGED -------------------------------------------
        self.fix_unit_weights = bool(fix_unit_weights)

        # legacy placeholders
        self.constraint = constraint
        self.cosine_threshold = cosine_threshold
        self.k = k
        self.dic = dic

        # model params
        self.params_ = None
        self.fitted_ = False

    # -----------------------------------------------------------------
    # Utilities (unchanged)
    # -----------------------------------------------------------------
    @staticmethod
    def _safe_softmax(z):
        z = z - z.max(axis=-1, keepdims=True)
        exp = np.exp(z)
        return exp / exp.sum(axis=-1, keepdims=True)

    def _make_features(self, prob_vec):
        base = prob_vec[0] + self.epsilon
        return np.log((prob_vec[1:] + self.epsilon) / base).astype(float)

    # -----------------------------------------------------------------
    # Parameter unpacking
    # -----------------------------------------------------------------
    def _unpack_params(self, params):
        """
        Return a (n_label, 2) matrix of [b_c, w_c].

        If `fix_unit_weights` is True, `params` has length (n_label‑1)
        and contains only biases; weights are set to 1.
        """
        if self.fix_unit_weights:                                    # <<< NEW / CHANGED
            b = params.reshape(self.n_label - 1, 1)                  # (C‑1,1)
            w = np.ones_like(b)                                      # (C‑1,1)
            non_ref = np.hstack([b, w])                              # (C‑1,2)
        else:
            non_ref = params.reshape(self.n_label - 1, 2)
        ref = np.zeros((1, 2))
        return np.vstack([ref, non_ref])

    # -----------------------------------------------------------------
    # Core probabilistic pieces
    # -----------------------------------------------------------------
    def _predict_proba_from_params(self, params, X):
        pm = self._unpack_params(params)
        logits = pm[1:, 0] + X * pm[1:, 1]
        logits = np.hstack([np.zeros((len(X), 1)), logits])
        return self._safe_softmax(logits)

    def _negative_log_likelihood(self, params, X, Y):
        P = self._predict_proba_from_params(params, X)
        return -np.log(P[np.arange(len(Y)), Y] + self.epsilon).sum()

    def _invariance_penalty(self, params, X, pairs):
        if not (self.use_invariance and pairs):
            return 0.0
        P = self._predict_proba_from_params(params, X)
        i_idx = np.fromiter((i for i, _ in pairs), int)
        j_idx = np.fromiter((j for _, j in pairs), int)
        if self.invariance_loss_type == "mse":
            return np.square(P[i_idx] - P[j_idx]).sum()
        elif self.invariance_loss_type == "l1":
            return np.abs(P[i_idx] - P[j_idx]).sum()
        else:  # "sym_ce"
            eps = self.epsilon
            P_i, P_j = P[i_idx], P[j_idx]
            return -(P_j * np.log(P_i + eps) + P_i * np.log(P_j + eps)).sum()

    # -----------------------------------------------------------------
    # upper‑angle hinge penalty
    # -----------------------------------------------------------------
    def _upper_angle_penalty(self, params):
        if not self.use_upper_soft_angle:
            return 0.0
        non_ref = self._unpack_params(params)[1:]
        norms = np.sqrt((non_ref ** 2).sum(axis=1) + 1e-12)
        cosines = non_ref[:, 1] / norms
        violations = np.maximum(0.0, self._cos_up - cosines)
        return violations.mean() if self.penalty_on == "average" else violations.sum()

    # -----------------------------------------------------------------
    # Full objective
    # -----------------------------------------------------------------
    def _objective(self, params, X, Y, pairs):
        return (
            self._negative_log_likelihood(params, X, Y)
            + self.lambda_invariance * self._invariance_penalty(params, X, pairs)
            + self.lambda_angle * self._upper_angle_penalty(params)
        )

    # -----------------------------------------------------------------
    # Training
    # -----------------------------------------------------------------
    def train(
        self,
        default_prompt_maker,
        feedforward,
        demonstration_set=None,
        k=4,
        demonstration_set_index=None,
    ):
        # ----------- synthetic calibration set -----------------------
        idx_sets = self._permutate(demonstration_set_index, k)
        probs, labels, qids = [], [], []
        for demo_and_query in idx_sets[:5000]:
            demo_idx, q_idx = demo_and_query[:k], demo_and_query[k]
            prompt = default_prompt_maker(
                [demonstration_set[j] for j in demo_idx],
                demonstration_set[q_idx][0],
            )
            probs.append(feedforward(prompt=prompt, label_space=self.label_space))
            labels.append(demonstration_set.get_label(q_idx))
            qids.append(q_idx)

        X = np.vstack([self._make_features(p) for p in probs])
        Y = np.fromiter((self.label_space.index(l) for l in labels), int)

        # invariance pairs
        qmap = defaultdict(list)
        for i, q in enumerate(qids):
            qmap[q].append(i)
        pairs = [(i1, i2) for idxs in qmap.values()
                 for i1 in idxs for i2 in idxs if i1 < i2]

        # -------------- optimisation vector size --------------------  # <<< NEW / CHANGED
        dim = (self.n_label - 1) if self.fix_unit_weights else (self.n_label - 1) * 2
        init = np.random.randn(dim)                                   # <<< NEW / CHANGED

        res = minimize(
            lambda p: self._objective(p, X, Y, pairs),
            init,
            method="BFGS",
            options={"maxiter": self.max_iter, "disp": self.verbose},
        )
        self.params_, self.fitted_ = res.x, True
        if self.verbose:
            print("[SCIPY]", res.message)

        # diagnostics dataframe
        P_cal = self._predict_proba_from_params(self.params_, X)
        return pd.DataFrame({
            "label": Y,
            "query_idx": qids,
            "pred": P_cal.argmax(axis=1),
            **{f"score_{c}": P_cal[:, c] for c in range(self.n_label)},
        })

    # -----------------------------------------------------------------
    # Inference (unchanged)
    # -----------------------------------------------------------------
    def inference(self, label_space_prob, full_vocab_prob, hidden_state):
        if not self.fitted_:
            raise RuntimeError("Model not fitted yet.")
        x = self._make_features(label_space_prob)
        probs = self._predict_proba_from_params(self.params_, x[None, :])[0]
        return probs.tolist()

    __call__ = inference

    # -----------------------------------------------------------------
    # Permutation helper (unchanged)
    # -----------------------------------------------------------------
    def _permutate(self, elements, k):
        from itertools import islice
        if k == 0:
            return [list(p) for p in itertools.permutations(elements, 1)]
        return list(islice(
            (
                list(base + (extra,))
                for base in itertools.permutations(elements, k)
                for extra in elements if extra not in base
            ),
            20000
        ))
