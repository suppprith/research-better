# Originality boilerplate whitelist

Phrases that overlap with published work because everyone writes them the same
way, not because anyone copied. Standard methods description, standard framing
sentences, standard dataset and metric language.

Without this list the overlap check fires on every methods section, and an
author who is shown fifteen matches on "we use a learning rate of" stops reading
the output. That is the failure mode this file exists to prevent, and it is
worse than missing a real match, because a tool nobody reads catches nothing.

Same format as the fluff lexicon: a `##` heading whose text reads like an
identifier starts a section, `key: value` lines set its defaults, and each
`- item` is a phrase. Matching is on normalized text, so case and punctuation
do not matter. Any other `##` heading is documentation.

## framing

note: Standard paper-structure sentences. Every venue has thousands of papers containing these words in this order.

- the remainder of this paper is organized as follows
- the rest of this paper is organized as follows
- the remainder of the paper is structured as follows
- section 2 reviews related work
- we conclude in section
- the paper is organized as follows
- to the best of our knowledge
- in this paper we propose
- in this paper we present
- the contributions of this paper are as follows
- our main contributions are summarized as follows
- extensive experiments demonstrate the effectiveness of
- we hope this work will inspire future research
- all code and data are available at

## experimental_setup

note: Standard training and evaluation description. There are only so many ways to say what learning rate you used.

- we use a learning rate of
- with a learning rate of
- trained for epochs with a batch size of
- we train the model for
- using the adam optimizer
- with the adamw optimizer
- we use early stopping with patience
- averaged over five random seeds
- averaged over three random seeds
- we report the mean and standard deviation over
- all experiments were run on a single
- we use the default hyperparameters
- the model was implemented in pytorch
- implemented using the huggingface transformers library
- we split the data into training validation and test sets
- following standard practice we
- unless otherwise stated we use

## metrics

note: Standard metric definitions. These are definitions, and a definition written differently is usually written wrong.

- precision is defined as the fraction of retrieved documents that are relevant
- recall is defined as the fraction of relevant documents that are retrieved
- the f1 score is the harmonic mean of precision and recall
- we report precision recall and f1
- mean average precision
- normalized discounted cumulative gain
- we evaluate using accuracy precision recall and f1
- statistical significance was assessed using a paired t-test
- we use bonferroni correction for multiple comparisons
- error bars denote one standard deviation

## datasets

note: Standard dataset descriptions. A public benchmark has one canonical description and most papers reuse it.

- the ms marco passage ranking dataset
- the natural questions dataset
- we evaluate on the trec deep learning track
- the imagenet dataset contains
- the cifar-10 dataset consists of
- we use the standard train test split
- the dataset is publicly available

## mathematical

note: Standard mathematical statements. Restating a definition is not copying it.

- where n is the number of documents in the collection
- where k is the number of clusters
- the objective function is defined as
- we minimize the cross-entropy loss
- subject to the constraint that
- it follows immediately from the definition that
- without loss of generality we assume
- the proof follows by induction on
