import numpy as np
import torch

from torch.utils.data import Dataset

class TrainDataset(Dataset):
    def __init__(self, triples, nentity, nrelation, negative_sample_size, mode):
        self.len = len(triples)
        self.triples = triples
        self.nentity = nentity # NOT USED - overridden by get_true_attr (TODO)
        self.nrelation = nrelation
        self.negative_sample_size = negative_sample_size
        self.mode = mode
        self.count = self.count_frequency(triples)
        self.true_head, self.true_tail = self.get_true_head_and_tail(self.triples)
        self.true_attr = self.get_true_attr(self.triples)

    def __len__(self):
        return self.len

    def __getitem__(self, idx):
        positive_sample = self.triples[idx]

        head, relation, tail, attr = positive_sample

        subsampling_weight = self.count[(head, relation)] + self.count[(tail, -relation-1)]
        subsampling_weight = torch.sqrt(1 / torch.Tensor([subsampling_weight]))

        negative_sample_list = []
        negative_sample_size = 0

        while negative_sample_size < self.negative_sample_size:
            # The 4 here is because [sub, pred, ob, attr] ->> limited to a single attribute [TODO]
            negative_sample = np.concatenate((
                np.random.randint(self.nentity, size=1),
                np.random.randint(self.nrelation, size=1),
                np.random.randint(self.nentity, size=1)
            ))

            negative_sample = np.concatenate((negative_sample, self.true_attr[negative_sample[0]]))
            if self.mode == 'head-batch':
                mask = np.in1d(
                    negative_sample[:3],
                    self.true_head[(relation, tail)],
                    assume_unique=True,
                    invert=True
                )
            elif self.mode == 'tail-batch':
                mask = np.in1d(
                    negative_sample[:3],
                    self.true_tail[(head, relation)],
                    assume_unique=True,
                    invert=True
                )
            else:
                raise ValueError('Training batch mode %s not supported' % self.mode)

            mask = np.concatenate((mask, np.arange(0, len(mask) - 1) + len(mask)))
            negative_sample = negative_sample[mask]
            
            if len(negative_sample) < 4:
                continue
            negative_sample_list.append(negative_sample)
            negative_sample_size += negative_sample.size

        # TODO(Next): The last item of the following list should be as long as necessary. And negative samples
        # should be the same size.
        # Big worry here is that adding loss from many different attributes will completely outweigh loss
        # from the actual graph structure. Must scale it.
        positive_sample = [positive_sample[0], positive_sample[1], positive_sample[2]] + positive_sample[3:][0]
        negative_sample = torch.from_numpy(negative_sample).float()
        positive_sample = torch.LongTensor(positive_sample) #TODO First 3 needs to be a longtensor, after that should be floats
        return positive_sample, negative_sample, subsampling_weight, self.mode

    @staticmethod
    def collate_fn(data):
        positive_sample = torch.stack([_[0] for _ in data], dim=0)
        negative_sample = torch.stack([_[1] for _ in data], dim=0)
        subsample_weight = torch.cat([_[2] for _ in data], dim=0)
        mode = data[0][3]
        return positive_sample, negative_sample, subsample_weight, mode

    @staticmethod
    def count_frequency(triples, start=4):
        count = {}
        for head, relation, tail, attr in triples:
            if (head, relation) not in count:
                count[(head, relation)] = start
            else:
                count[(head, relation)] += 1

            if (tail, -relation-1) not in count:
                count[(tail, -relation-1)] = start
            else:
                count[(tail, -relation-1)] += 1
        return count

    def get_true_attr(self, triples):
        true_attr = {}
        for head, relation, tail, attr in triples:
            true_attr[head] = attr
        self.nentity = len(true_attr)
        return true_attr

    @staticmethod
    def get_true_head_and_tail(triples):

        true_head = {}
        true_tail = {}

        for head, relation, tail, attr in triples:
            if (head, relation) not in true_tail:
                true_tail[(head, relation)] = []
            true_tail[(head, relation)].append(tail)
            if (relation, tail) not in true_head:
                true_head[(relation, tail)] = []
            true_head[(relation, tail)].append(head)

        for relation, tail in true_head:
            true_head[(relation, tail)] = np.array(list(set(true_head[(relation, tail)])))
        for head, relation in true_tail:
            true_tail[(head, relation)] = np.array(list(set(true_tail[(head, relation)])))

        return true_head, true_tail

class BidirectionalOneShotIterator(object):
    def __init__(self, dataloader_head, dataloader_tail):
        self.iterator_head = self.one_shot_iterator(dataloader_head)
        self.iterator_tail = self.one_shot_iterator(dataloader_tail)
        self.step = 0

    def __next__(self):
        self.step += 1
        if self.step % 2 == 0:
            data = next(self.iterator_head)
        else:
            data = next(self.iterator_tail)
        return data

    @staticmethod
    def one_shot_iterator(dataloader):
        while True:
            for data in dataloader:
                yield data
